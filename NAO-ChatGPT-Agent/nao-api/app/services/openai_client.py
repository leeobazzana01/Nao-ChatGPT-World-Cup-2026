#services/openai_client.py —> HTTP client for the OpenAI API

import json
import ssl
import time
import uuid
import io
import urllib.request
import urllib.error
import http.client
import threading
from typing import Optional, Any
from app.utils import logger as log_module

_log = log_module.get("openai_client")

_OPENAI_HOST = "api.openai.com"
_OPENAI_BASE = "/v1"

# HTTPS connection pool (one per thread for thread-safety)
_conn_local = threading.local()


def _get_conn(timeout: int) -> http.client.HTTPSConnection:
    """Gets or creates a reusable HTTPS connection for the current thread."""
    conn: Optional[http.client.HTTPSConnection] = getattr(_conn_local, "conn", None)
    if conn is None:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(_OPENAI_HOST, timeout=timeout, context=ctx)
        _conn_local.conn = conn
        _log.debug("New HTTPS connection created for thread")
    return conn


def _reset_conn(timeout: int) -> http.client.HTTPSConnection:
    """Forces a new connection (after a network error)."""
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(_OPENAI_HOST, timeout=timeout, context=ctx)
    _conn_local.conn = conn
    return conn


#base request 
def _request_json(
    method: str,
    path: str,
    api_key: str,
    body: Optional[bytes] = None,
    content_type: str = "application/json",
    timeout: int = 60,
    retries: int = 3,
) -> dict:
    
    #performs a JSON request to the OpenAI API with automatic retry
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": content_type,
        "User-Agent": "nao-api/1.0",
    }
    if body:
        headers["Content-Length"] = str(len(body))

    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            conn = _get_conn(timeout)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status

            if status == 200:
                return json.loads(raw.decode("utf-8"))

            #recoverable errors: 429 (rate limit), 500, 502, 503
            if status in (429, 500, 502, 503) and attempt < retries:
                wait = 2 ** attempt
                _log.warning(f"OpenAI HTTP {status} — waiting {wait}s (attempt {attempt})")
                time.sleep(wait)
                conn = _reset_conn(timeout)
                continue

            error_body = json.loads(raw.decode("utf-8")) if raw else {}
            msg = error_body.get("error", {}).get("message", f"HTTP {status}")
            raise OpenAIError(f"OpenAI API error {status}: {msg}", status_code=status)

        except (http.client.RemoteDisconnected,
                http.client.CannotSendRequest,
                ConnectionResetError,
                BrokenPipeError,
                TimeoutError) as exc:
            _log.warning(f"Connection lost (attempt {attempt}): {exc}")
            last_exc = exc
            conn = _reset_conn(timeout)
            if attempt < retries:
                time.sleep(2 ** attempt)
        except OpenAIError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 ** attempt)

    raise OpenAIError(f"Failed after {retries} attempts: {last_exc}") from last_exc


#multipart for Whisper  
def _build_multipart(fields: dict[str, str], file_field: str,
                     filename: str, file_data: bytes,
                     content_type_file: str = "audio/ogg") -> tuple[bytes, str]:
    
    #builds a multipart/form data body for a file upload
    boundary = f"NaoApiBoundary{uuid.uuid4().hex}"
    buf = io.BytesIO()

    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(value.encode("utf-8"))
        buf.write(b"\r\n")

    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    )
    buf.write(f"Content-Type: {content_type_file}\r\n\r\n".encode())
    buf.write(file_data)
    buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())

    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"

#whisper audio transcription                                           
def transcribe_audio(
    audio_data: bytes,
    filename: str,
    api_key: str,
    model: str = "whisper-1",
    language: Optional[str] = None,
    timeout: int = 60,
) -> str:
    #transcribes the audio file and returns transcribed text
    t0 = time.perf_counter()

    #dettecting content type from the file name
    ext = filename.rsplit(".", 1)[-1].lower()
    mime_map = {"ogg": "audio/ogg", "wav": "audio/wav", "mp3": "audio/mpeg",
                "m4a": "audio/mp4", "webm": "audio/webm"}
    audio_mime = mime_map.get(ext, "audio/ogg")

    fields: dict[str, str] = {"model": model}
    if language:
        fields["language"] = language
    fields["response_format"] = "text"

    body, ct = _build_multipart(fields, "file", filename, audio_data, audio_mime)

    result = _request_json(
        "POST",
        f"{_OPENAI_BASE}/audio/transcriptions",
        api_key,
        body=body,
        content_type=ct,
        timeout=timeout,
    )

    elapsed = time.perf_counter() - t0
    #whisper with response_format text returns a raw string (no JSON wrapper), but our parser expects a dict adjust accordingly:
    
    if isinstance(result, str):
        text = result.strip()
    else:
        text = result.get("text", "").strip()

    _log.info(f"Whisper: {len(audio_data):,}B -> {len(text)} chars in {elapsed:.2f}s")
    return text


#variant->  whisper returns text/plain, not JSON
def transcribe_audio_raw(
    audio_data: bytes,
    filename: str,
    api_key: str,
    model: str = "whisper-1",
    language: Optional[str] = None,
    timeout: int = 60,
) -> str:
    
    #variant that correctly handles the text/plain response from Whisper
    t0 = time.perf_counter()
    ext = filename.rsplit(".", 1)[-1].lower()
    mime_map = {"ogg": "audio/ogg", "wav": "audio/wav", "mp3": "audio/mpeg",
                "m4a": "audio/mp4", "webm": "audio/webm"}
    
    audio_mime = mime_map.get(ext, "audio/ogg")

    fields: dict[str, str] = {"model": model, "response_format": "text"}
    if language:
        fields["language"] = language

    body, ct = _build_multipart(fields, "file", filename, audio_data, audio_mime)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": ct,
        "User-Agent": "nao-api/1.0",
        "Content-Length": str(len(body)),
    }

    last_exc = None
    for attempt in range(1, 4):
        try:
            conn = _get_conn(timeout)
            conn.request("POST", f"{_OPENAI_BASE}/audio/transcriptions",
                         body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status == 200:
                text = raw.decode("utf-8").strip()
                elapsed = time.perf_counter() - t0
                _log.info(f"Whisper: {len(audio_data):,}B -> {len(text)} chars in {elapsed:.2f}s")
                return text
            if resp.status in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                conn = _reset_conn(timeout)
                continue
            raise OpenAIError(f"Whisper HTTP {resp.status}: {raw[:200]}")
        except OpenAIError:
            raise
        except Exception as exc:
            last_exc = exc
            conn = _reset_conn(timeout)
            if attempt < 3:
                time.sleep(2 ** attempt)

    raise OpenAIError(f"Whisper failed after 3 attempts: {last_exc}") from last_exc


#GPT chat completions 
def chat_completion(
    messages: list[dict],
    api_key: str,
    model: str = "gpt-4o",
    max_tokens: int = 300,
    temperature: float = 0.7,
    timeout: int = 60,
) -> str:
    #calls GPT to complete a conversation and returns assistant's reply text
    
    t0 = time.perf_counter()

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    result = _request_json(
        "POST",
        f"{_OPENAI_BASE}/chat/completions",
        api_key,
        body=body,
        timeout=timeout,
    )

    reply = result["choices"][0]["message"]["content"].strip()
    usage = result.get("usage", {})
    elapsed = time.perf_counter() - t0
    _log.info(
        f"GPT ({model}): {usage.get('prompt_tokens',0)}->{usage.get('completion_tokens',0)} tokens "
        f"in {elapsed:.2f}s"
    )
    return reply

#error                                     
class OpenAIError(Exception):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code
