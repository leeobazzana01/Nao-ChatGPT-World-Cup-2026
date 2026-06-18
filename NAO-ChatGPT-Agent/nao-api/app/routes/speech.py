#routes/speech.py —> handler for the robot's main endpoint

import re
import hashlib
import time
import threading
import concurrent.futures
from typing import Optional, TYPE_CHECKING
from http.server import BaseHTTPRequestHandler

from app.utils.multipart import parse as parse_multipart, MultipartParseError
from app.utils.responses import send_text, send_error
from app.utils import logger as log_module

if TYPE_CHECKING:
    from app.server import NaoAPIServer

_log = log_module.get("speech")

#rout regex —> captures all path params
_ROUTE_RE = re.compile(
    r"^/speech"
    r"/id/(?P<chat_id>[^/]+)"
    r"/culture/(?P<culture>[^/]+)"
    r"/raw/(?P<raw>[^/]+)"
    r"/persona/(?P<persona>[^/]+)"
    r"/responselength/(?P<response_length>[^/]+)"
    r"/ai-version/(?P<ai_version>[^/]+)"
    r"/?$",
    re.IGNORECASE,
)


def matches(path: str) -> bool:
    return bool(_ROUTE_RE.match(path))


def handle(handler: BaseHTTPRequestHandler, server: "NaoAPIServer") -> None:
    #handler entry point —> called by the server dispatcher 
    t0 = time.perf_counter()
    client_ip = handler.client_address[0]

    #parse the route 
    m = _ROUTE_RE.match(handler.path)
    if not m:
        send_error(handler, "Invalid route", 400)
        return

    params = m.groupdict()
    chat_id        = _sanitize(params["chat_id"], 64)
    culture        = _sanitize(params["culture"], 10)
    persona        = _sanitize(params["persona"], 80)
    response_length = _sanitize(params["response_length"], 20).lower()
    ai_version     = _sanitize(params["ai_version"], 40)

    #mormalize response_length
    if response_length not in ("short", "medium", "standard"):
        response_length = "short"

    _log.info(
        f"[{client_ip}] POST /speech | session={chat_id[:8]} "
        f"persona={persona} len={response_length} model={ai_version}"
    )
    
    #authentication
    auth = handler.headers.get("Authorization", "")
    if auth != server.config.AUTH_TOKEN:
        _log.warning(f"[{client_ip}] Invalid token: {auth!r}")
        send_error(handler, "Unauthorized", 401)
        return

    #rate limiting
    if not server.rate_ip.allow(client_ip):
        _log.warning(f"[{client_ip}] Rate limit per IP")
        send_error(handler, "Too Many Requests", 429)
        return

    if not server.rate_session.allow(chat_id):
        _log.warning(f"[{client_ip}] Rate limit per session {chat_id[:8]}")
        send_error(handler, "Too Many Requests (session)", 429)
        return

    #reading the body
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length > server.config.REQUEST_MAX_SIZE_BYTES:
        send_error(handler, "Payload Too Large", 413)
        return

    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        send_error(handler, "Content-Type must be multipart/form-data", 415)
        return

    try:
        body = handler.rfile.read(content_length)
    except Exception as exc:
        _log.error(f"Error reading body: {exc}")
        send_error(handler, "Error reading request", 400)
        return

    #multipart parsing
    try:
        form = parse_multipart(body, content_type)
    except MultipartParseError as exc:
        _log.error(f"Multipart parse error: {exc}")
        send_error(handler, f"Invalid multipart: {exc}", 400)
        return

    audio_file = form.get_file("audio")
    photo_file = form.get_file("photo")

    if not audio_file and not photo_file:
        send_error(handler, "No file (audio/photo) provided", 400)
        return

    _log.debug(
        f"  audio={audio_file and f'{audio_file.filename} {audio_file.size:,}B'} "
        f"  photo={photo_file and f'{photo_file.filename} {photo_file.size:,}B'}"
    )

    #deduplication 
    req_hash = _request_hash(chat_id, audio_file.data if audio_file else b"")
    if server.sessions.is_duplicate(chat_id, req_hash):
        _log.info(f"  Duplicate request — returning 'skip'")
        send_text(handler, "skip")
        return
    server.sessions.mark_request(chat_id, req_hash)

    #transcription + STOP detection
    user_text = ""
    language = _culture_to_lang(culture)

    if audio_file:
        transcript = server.transcription.transcribe(
            audio_data=audio_file.data,
            filename=audio_file.filename or "recording.ogg",
            language=language,
        )

        if not transcript.ok:
            _log.error(f"Transcription failed: {transcript.error}")
            #try to continue without text if there is an image
            if not photo_file:
                send_text(handler, "")
                return
        else:
            user_text = transcript.text
            _log.info(f"  Transcription: {user_text!r}")

            #detect STOP
            if transcript.is_stop_command:
                _log.info(f"  STOP command detected")
                send_text(handler, "STOP")
                return

    #fallback if there is only an image
    if not user_text and photo_file:
        user_text = "Please describe what you see in the image."

    if not user_text:
        send_text(handler, "")
        return

    #GPT + RAG
    result = server.chat.respond(
        chat_id=chat_id,
        persona=persona,
        culture=culture,
        response_length=response_length,
        ai_version=ai_version,
        user_text=user_text,
        image_data=photo_file.data if photo_file else None,
        image_filename=(photo_file.filename if photo_file else "image.jpg"),
    )

    elapsed = time.perf_counter() - t0

    if not result.ok:
        _log.error(f"  GPT failed: {result.error}")
        send_text(handler, "")
        return

    _log.info(
        f"  Reply ({result.model}): {len(result.reply)} chars | "
        f"total={elapsed:.2f}s (whisper+gpt={result.elapsed:.2f}s)"
    )

    send_text(handler, result.reply)


#helpers
def _sanitize(value: str, max_len: int) -> str:
    #removes dangerous characters and truncates
    safe = re.sub(r"[^\w\-. ]", "", value)
    return safe[:max_len].strip()


def _culture_to_lang(culture: str) -> Optional[str]:
    #converts 'en-GB' -> 'en' for Whisper
    parts = culture.lower().replace("_", "-").split("-")
    return parts[0] if parts and len(parts[0]) == 2 else None


def _request_hash(chat_id: str, audio_data: bytes) -> str:
    #hash for deduplication: combines session + first 4KB of audio
    h = hashlib.md5()
    h.update(chat_id.encode())
    h.update(audio_data[:4096])
    return h.hexdigest()
