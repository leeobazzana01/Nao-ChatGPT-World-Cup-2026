#services/transcription.py —> audio transcription via Whisper with caching

import hashlib
import threading
from typing import Optional
from app.services import openai_client as oai
from app.utils import logger as log_module

_log = log_module.get("transcription")

#multilingual "stop" detection phrases
_STOP_PHRASES = {
    "no", "no.", "no!", "stop", "stop.", "exit", "quit", "bye", "goodbye",
    
    #portuguese
    "não", "não.", "pare", "parar", "tchau", "sair", "encerrar", "encerre", 
    
    #spanish
    "no.", "detente", "parar", "salir",
    #french
    "non", "arrêtez", "quitter",
    #german
    "nein", "stopp", "aufhören",
}


class TranscriptionService:
    #audio transcription service

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        timeout: int = 30,
        cache_size: int = 200,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._cache: dict[str, str] = {}
        self._cache_order: list[str] = []   #LRU order
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def transcribe(
        self,
        audio_data: bytes,
        filename: str = "recording.ogg",
        language: Optional[str] = None,
    ) -> "TranscriptionResult":

        #transcribes the audio and returns a TranscriptionResult, with text, is_stop_command and from_cache
        
        #hash for cache and deduplication
        audio_hash = hashlib.md5(audio_data).hexdigest()

        #checking cache
        cached = self._cache_get(audio_hash)
        if cached is not None:
            _log.debug(f"Transcription from cache: hash={audio_hash[:8]}")
            return TranscriptionResult(
                text=cached,
                is_stop_command=self._is_stop(cached),
                from_cache=True,
                audio_hash=audio_hash,
            )

        #calling whisper
        try:
            text = oai.transcribe_audio_raw(
                audio_data=audio_data,
                filename=filename,
                api_key=self._api_key,
                model=self._model,
                language=language,
                timeout=self._timeout,
            )
        except oai.OpenAIError as exc:
            _log.error(f"Whisper error: {exc}")
            return TranscriptionResult(
                text="",
                is_stop_command=False,
                from_cache=False,
                audio_hash=audio_hash,
                error=str(exc),
            )

        #store in cache
        self._cache_set(audio_hash, text)

        return TranscriptionResult(
            text=text,
            is_stop_command=self._is_stop(text),
            from_cache=False,
            audio_hash=audio_hash,
        )

    #internals 

    def _is_stop(self, text: str) -> bool:
        #checks whether the text is a stop command

        normalized = text.strip().lower().rstrip(".!?,;")
        return normalized in _STOP_PHRASES

    def _cache_get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._cache.get(key)

    def _cache_set(self, key: str, value: str) -> None:
        with self._lock:
            if key not in self._cache:
                self._cache_order.append(key)
                #evict LRU if necessary
                if len(self._cache_order) > self._cache_size:
                    oldest = self._cache_order.pop(0)
                    self._cache.pop(oldest, None)
            self._cache[key] = value


class TranscriptionResult:
    __slots__ = ("text", "is_stop_command", "from_cache", "audio_hash", "error")

    def __init__(
        self,
        text: str,
        is_stop_command: bool,
        from_cache: bool,
        audio_hash: str,
        error: Optional[str] = None,
    ) -> None:
        self.text = text
        self.is_stop_command = is_stop_command
        self.from_cache = from_cache
        self.audio_hash = audio_hash
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None

    def __repr__(self) -> str:
        return (f"<TranscriptionResult text={self.text[:40]!r} "
                f"stop={self.is_stop_command} cache={self.from_cache}>")
