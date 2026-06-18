#config.py loads configuration from the .env file and environment variables.

import os
import pathlib

#locate the .env file at the project root 
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()
_ENV_FILE = _PROJECT_ROOT / ".env"


def _load_env_file(path: pathlib.Path) -> None:
    #loading variables from a .env file into os.environ (without overriding)
    
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:          #do not override system env
                os.environ[key] = value


_load_env_file(_ENV_FILE)

#helpers                                                            
def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _get_int(key: str, default: int = 0) -> int:
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


def _get_bool(key: str, default: bool = False) -> bool:
    return _get(key, str(default)).lower() in ("1", "true", "yes", "on")


#exported configuration                                            
#OpenAI setup
OPENAI_API_KEY: str   = _get("OPENAI_API_KEY", "")
OPENAI_CHAT_MODEL: str = _get("OPENAI_CHAT_MODEL", "gpt-4o")
OPENAI_WHISPER_MODEL: str = _get("OPENAI_WHISPER_MODEL", "whisper-1")
OPENAI_TIMEOUT: int   = _get_int("OPENAI_TIMEOUT", 60)

#server
HOST: str = _get("HOST", "0.0.0.0")
PORT: int = _get_int("PORT", 8080)

#auth
AUTH_TOKEN: str = _get("AUTH_TOKEN", "change-this-auth-token")

#sessions
SESSION_TTL_SECONDS: int = _get_int("SESSION_TTL_SECONDS", 3600)
SESSION_MAX_HISTORY: int = _get_int("SESSION_MAX_HISTORY", 30)

#RAG
KNOWLEDGE_DIR: pathlib.Path = pathlib.Path(_get("KNOWLEDGE_DIR", str(_PROJECT_ROOT / "data" / "knowledge")))
RAG_TOP_K: int   = _get_int("RAG_TOP_K", 5)
RAG_CHUNK_SIZE: int = _get_int("RAG_CHUNK_SIZE", 800)

#rate limiting
RATE_LIMIT_PER_IP: int      = _get_int("RATE_LIMIT_PER_IP", 30)
RATE_LIMIT_PER_SESSION: int = _get_int("RATE_LIMIT_PER_SESSION", 20)

#logging
LOG_LEVEL: str = _get("LOG_LEVEL", "INFO").upper()
LOG_DIR: pathlib.Path = pathlib.Path(_get("LOG_DIR", str(_PROJECT_ROOT / "logs")))

#limits
REQUEST_MAX_SIZE_MB: int = _get_int("REQUEST_MAX_SIZE_MB", 25)
REQUEST_MAX_SIZE_BYTES: int = REQUEST_MAX_SIZE_MB * 1024 * 1024

#default both persona and language
DEFAULT_PERSONA: str   = _get("DEFAULT_PERSONA", "torcedor-brasileiro")
DEFAULT_LANGUAGE: str  = _get("DEFAULT_LANGUAGE", "pt-br")

#personas (loaded from disk, same pattern as the knowledge base)
PERSONAS_DIR: pathlib.Path = pathlib.Path(
    _get("PERSONAS_DIR", str(_PROJECT_ROOT / "data" / "personas"))
)

#copa (World Cup feature)
COPA_ENABLED: bool = _get_bool("COPA_ENABLED", True)
#optional real-time source for GET /copa/live; empty -> offline (dict only)
COPA_LIVE_SOURCE_URL: str = _get("COPA_LIVE_SOURCE_URL", "")
#how often the scheduler checks for matches that just finished (seconds)
COPA_SCHEDULER_TICK_SECONDS: int = _get_int("COPA_SCHEDULER_TICK_SECONDS", 60)

#internal paths
SESSIONS_DIR: pathlib.Path = _PROJECT_ROOT / "data" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

#validation on import                                              
def validate() -> list[str]:
    #returns a list of configuration warnings/errors
    warnings: list[str] = []
    if not OPENAI_API_KEY:
        warnings.append("OPENAI_API_KEY is not set — OpenAI calls will fail.")
    if AUTH_TOKEN in ("change-this-auth-token", ""):
        warnings.append("AUTH_TOKEN still has its default value — change it in production.")
    return warnings
