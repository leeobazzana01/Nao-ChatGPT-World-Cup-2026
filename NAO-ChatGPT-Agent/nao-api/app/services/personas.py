#services/personas.py —> loads persona definitions from disk.
#same idea as KnowledgeBase: drop a .txt in data/personas/ and it is
#available by its slug (filename without extension), editable without deploy.

import pathlib
import threading
from typing import Optional
from app.utils import logger as log_module

_log = log_module.get("personas")


class PersonaManager:
    #maps slug -> persona text. The chat layer injects this text as the
    #robot's identity in the system prompt.

    def __init__(self, personas_dir: pathlib.Path, default_slug: str = "") -> None:
        self._dir = personas_dir
        self._default_slug = self._slugify(default_slug)
        self._personas: dict[str, str] = {}
        self._lock = threading.Lock()

    #loading
    def load(self) -> int:
        #reads every *.txt -> returns how many personas were loaded
        with self._lock:
            self._personas = {}
            for path in sorted(self._dir.glob("*.txt")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace").strip()
                    if text:
                        self._personas[path.stem.lower()] = text
                        _log.info(f"  Loaded persona: {path.stem}")
                except Exception as exc:
                    _log.error(f"Error reading persona {path}: {exc}")
            return len(self._personas)

    def reload(self) -> int:
        return self.load()

    #lookup
    def get(self, slug: str) -> Optional[str]:
        #returns persona text for a slug, falling back to the default
        key = self._slugify(slug)
        with self._lock:
            if key in self._personas:
                return self._personas[key]
            if self._default_slug in self._personas:
                return self._personas[self._default_slug]
            return None

    @property
    def count(self) -> int:
        return len(self._personas)

    @staticmethod
    def _slugify(name: str) -> str:
        #"Torcedor Brasileiro" / "torcedor_brasileiro" -> "torcedor-brasileiro"
        return name.strip().lower().replace(" ", "-").replace("_", "-")
