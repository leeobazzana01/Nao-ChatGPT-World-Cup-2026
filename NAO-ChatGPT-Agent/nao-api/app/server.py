"""
server.py — Main HTTP server for the NAO API.

Uses ThreadingHTTPServer (stdlib) with a thread pool.
Each request runs in a separate thread.
Services are instantiated once and shared (thread-safe).
"""

import sys
import os
import signal
import threading
import time
import pathlib
import collections
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

#adding the project root to the path
_HERE = pathlib.Path(__file__).parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

#internal imports (after sys.path)
import app.config as config
from app.utils import logger as log_module
from app.utils.rate_limiter import RateLimiter
from app.utils.responses import send_text, send_error, send_cors_preflight
from app.services.sessions import SessionManager
from app.services.knowledge import KnowledgeBase
from app.services.transcription import TranscriptionService
from app.services.chat import ChatService
from app.services.personas import PersonaManager
from app.services.copa_service import CopaService
from app.routes import speech as speech_route
from app.routes import health as health_route
from app.routes import copa as copa_route

#logging                                                           
log_module.setup(config.LOG_DIR, config.LOG_LEVEL)
_log = log_module.get("server")

#service container                                                
class NaoAPIServer:
    #holds all instantiated services.
    #passed to the handlers via a reference on the HTTP server.
    

    def __init__(self) -> None:
        self.config = config

        #telemetry counters
        self.counters: collections.Counter = collections.Counter()
        self._counter_lock = threading.Lock()

        #rate limiters
        self.rate_ip      = RateLimiter(config.RATE_LIMIT_PER_IP, 60)
        self.rate_session = RateLimiter(config.RATE_LIMIT_PER_SESSION, 60)

        #sessions
        self.sessions = SessionManager(
            sessions_dir=config.SESSIONS_DIR,
            ttl_seconds=config.SESSION_TTL_SECONDS,
            max_history=config.SESSION_MAX_HISTORY,
        )

        #knowledge base (RAG)
        self.knowledge = KnowledgeBase(
            knowledge_dir=config.KNOWLEDGE_DIR,
            chunk_size=config.RAG_CHUNK_SIZE,
        )

        #personas (loaded from disk)
        self.personas = PersonaManager(
            personas_dir=config.PERSONAS_DIR,
            default_slug=config.DEFAULT_PERSONA,
        )

        #copa (World Cup feature) — None if disabled
        self.copa: Optional[CopaService] = None
        if config.COPA_ENABLED:
            self.copa = CopaService(
                knowledge=self.knowledge,
                knowledge_dir=config.KNOWLEDGE_DIR,
                live_source_url=config.COPA_LIVE_SOURCE_URL,
                tick_seconds=config.COPA_SCHEDULER_TICK_SECONDS,
            )

        #transcription (Whisper)
        self.transcription = TranscriptionService(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_WHISPER_MODEL,
            timeout=min(config.OPENAI_TIMEOUT, 30),
        )

        #chat (GPT + RAG)
        self.chat = ChatService(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_CHAT_MODEL,
            sessions=self.sessions,
            knowledge=self.knowledge,
            personas=self.personas,
            copa=self.copa,
            timeout=config.OPENAI_TIMEOUT,
        )

    def inc(self, key: str) -> None:
        with self._counter_lock:
            self.counters[key] += 1

    def startup(self) -> None:
        #initializes asynchronous services
        
        _log.info("Loading knowledge base (RAG)...")
        n = self.knowledge.load()
        if n:
            _log.info(f"  RAG ready: {n} chunks")
        else:
            _log.warning("  RAG empty — add .txt/.md files to data/knowledge/")

        #personas
        p = self.personas.load()
        _log.info(f"Personas loaded: {p}")

        #copa scheduler (writes copa_resultados.txt + reloads RAG)
        if self.copa:
            self.copa.start_scheduler()

        warnings = config.validate()
        for w in warnings:
            _log.warning(f"  CONFIG: {w}")

        #periodic cleanup task (every 10 minutes)
        self._start_cleanup_task()

    def _start_cleanup_task(self) -> None:
        def _cleanup():
            while True:
                time.sleep(600)
                try:
                    removed = self.sessions.purge_expired()
                    cleaned = self.rate_ip.cleanup() + self.rate_session.cleanup()
                    if removed or cleaned:
                        _log.debug(f"Cleanup: {removed} sessions, {cleaned} buckets")
                except Exception as exc:
                    _log.error(f"Cleanup error: {exc}")

        t = threading.Thread(target=_cleanup, daemon=True, name="cleanup")
        t.start()

#HTTP handler                                                      
class _Handler(BaseHTTPRequestHandler):
    #HTTP handler that delegates to the routes, reference to NaoAPIServer lives on self.server._nao_server.
    

    #silencing the default BaseHTTPServer access logs (we use our own)
    def log_message(self, format: str, *args) -> None:
        pass

    def log_error(self, format: str, *args) -> None:
        _log.error(format % args)

    @property
    def _svc(self) -> NaoAPIServer:
        return self.server._nao_server  # type: ignore[attr-defined]

    #GET
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/dashboard"):
            health_route.handle_dashboard(self, self._svc)
        elif path == "/health":
            health_route.handle_health(self, self._svc)
        elif path == "/status":
            health_route.handle_status(self, self._svc)
        elif copa_route.matches(path):
            copa_route.handle(self, self._svc)
        else:
            send_error(self, "Not Found", 404)

    #POST
    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        svc = self._svc

        if speech_route.matches(path):
            svc.inc("requests_total")
            try:
                speech_route.handle(self, svc)
                #count the results (send_text was already called)
                svc.inc("requests_ok")
            except Exception as exc:
                _log.error(f"Unhandled error in speech: {exc}", exc_info=True)
                svc.inc("requests_error")
                try:
                    send_text(self, "")
                except Exception:
                    pass

        elif path == "/admin/reload-knowledge":
            health_route.handle_reload_knowledge(self, svc)

        else:
            send_error(self, "Not Found", 404)

    #OPTIONS (CORS preflight)
    def do_OPTIONS(self) -> None:
        send_cors_preflight(self)


#HTTP server with a custom thread pool                             
class _ThreadedServer(ThreadingHTTPServer):
    #threadingHTTPServer with a reference to the service container

    def __init__(self, server_address, handler_class, nao_server: NaoAPIServer) -> None:
        super().__init__(server_address, handler_class)
        self._nao_server = nao_server
        #raise the socket backlog to absorb spikes
        self.socket.listen(128)

#entrypoint                                                        
def main() -> None:
    #banner
    print(f"""
╔══════════════════════════════════════════════════════╗
║          NAO V5 ↔ ChatGPT API  v1.0                  ║
║  Bridge server for integration with OpenAI           ║
╚══════════════════════════════════════════════════════╝
""")

    #inicializating services
    nao_server = NaoAPIServer()
    nao_server.startup()

    #starting the HTTP server
    addr = (config.HOST, config.PORT)
    httpd = _ThreadedServer(addr, _Handler, nao_server)

    _log.info(f"Server listening on http://{config.HOST}:{config.PORT}")
    _log.info(f"Dashboard: http://localhost:{config.PORT}/")
    _log.info(f"Health:    http://localhost:{config.PORT}/health")
    _log.info(f"Status:    http://localhost:{config.PORT}/status")
    _log.info("")
    _log.info("NAO configuration (Choregraphe):")
    _log.info(f"  CHATGPT SERVER  -> <THIS_MACHINE_IP>:{config.PORT}")
    _log.info(f"  AUTH_TOKEN      -> {config.AUTH_TOKEN}")
    _log.info(f"  Press Ctrl+C to stop")

    #graceful shutdown
    def _shutdown(sig, frame):
        _log.info("Shutting down server...")
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    _log.info("Server stopped.")


if __name__ == "__main__":
    main()
