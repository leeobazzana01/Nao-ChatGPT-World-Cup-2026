#services/sessions.py —> Conversation session management.

#storing a message history in JSON files keyed by chat_id
#thread safe via a per session lock


import json
import time
import threading
import pathlib
from typing import Optional
from app.utils import logger as log_module

_log = log_module.get("sessions")


class SessionManager:
    #manages chat sessions for the NAO robot

    def __init__(
        self,
        sessions_dir: pathlib.Path,
        ttl_seconds: int = 3600,
        max_history: int = 30,
    ) -> None:
        self._dir = sessions_dir
        self._ttl = ttl_seconds
        self._max_history = max_history
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)
        _log.info(f"SessionManager started | dir={self._dir} | ttl={ttl_seconds}s")

    #public API
    def get_history(self, chat_id: str) -> list[dict]:
        #returns the session's message history

        data = self._load(chat_id)
        return data.get("messages", [])

    def append_messages(self, chat_id: str, persona: str, new_messages: list[dict]) -> None:
        #appends messages to the history and persists it

        with self._lock_for(chat_id):
            data = self._load(chat_id)
            data.setdefault("messages", [])
            data["messages"].extend(new_messages)
            data["messages"] = data["messages"][-self._max_history:]
            data["last_seen"] = time.time()
            data["persona"] = persona
            self._save(chat_id, data)

    def is_duplicate(self, chat_id: str, request_hash: str) -> bool:

        #checks whether this request was already processed (anti-duplicate)
        data = self._load(chat_id)
        hashes = data.get("request_hashes", [])
        return request_hash in hashes

    def mark_request(self, chat_id: str, request_hash: str) -> None:
        #recording the request hash for deduplication

        with self._lock_for(chat_id):
            data = self._load(chat_id)
            hashes = data.get("request_hashes", [])
            hashes.append(request_hash)
            data["request_hashes"] = hashes[-50:]   #keep only the last 50
            self._save(chat_id, data)

    def clear(self, chat_id: str) -> None:
        #removing the session from the disk

        path = self._path(chat_id)
        if path.exists():
            path.unlink()
        _log.info(f"Session removed: {chat_id}")

    def stats(self) -> dict:
    #returns global session statistics

        sessions = list(self._dir.glob("*.json"))
        active = expired = 0
        now = time.time()
        for s in sessions:
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
                if now - data.get("last_seen", 0) < self._ttl:
                    active += 1
                else:
                    expired += 1
            except Exception:
                pass
        return {
            "total": len(sessions),
            "active": active,
            "expired": expired,
        }

    def purge_expired(self) -> int:
        #removing expired sessions, returning the numbers removed

        removed = 0
        now = time.time()
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if now - data.get("last_seen", 0) > self._ttl:
                    path.unlink()
                    removed += 1
            except Exception:
                pass
        if removed:
            _log.info(f"Expired sessions removed: {removed}")
        return removed

    #internals         

    def _path(self, chat_id: str) -> pathlib.Path:
        
        #sanitize to avoid path traversal
        safe_id = "".join(c for c in chat_id if c.isalnum() or c in "-_")[:64]
        return self._dir / f"{safe_id}.json"

    def _load(self, chat_id: str) -> dict:
        path = self._path(chat_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                _log.warning(f"Error loading session {chat_id}: {exc}")
        return {
            "chat_id": chat_id,
            "created_at": time.time(),
            "last_seen": time.time(),
            "messages": [],
            "persona": "",
            "request_hashes": [],
        }

    def _save(self, chat_id: str, data: dict) -> None:
        path = self._path(chat_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _lock_for(self, chat_id: str) -> threading.Lock:
        with self._global_lock:
            if chat_id not in self._locks:
                self._locks[chat_id] = threading.Lock()
            return self._locks[chat_id]
