#routes/health.py -> health, status and web dashboard endpoints.

import time
import json
import pathlib
from http.server import BaseHTTPRequestHandler
from app.utils.responses import send_json, send_html, send_text
from app.utils import logger as log_module

_log = log_module.get("health")
_START_TIME = time.time()


def handle_health(handler: BaseHTTPRequestHandler, server) -> None:
    #GET /health —> liveness probe

    send_json(handler, {
        "status": "ok",
        "uptime_seconds": round(time.time() - _START_TIME),
        "version": "1.0.0",
    })


def handle_status(handler: BaseHTTPRequestHandler, server) -> None:
    #GET /status -> detailed metrics
    
    session_stats = server.sessions.stats()
    kb_chunks = server.knowledge.chunk_count if server.knowledge else 0

    send_json(handler, {
        "status": "ok",
        "uptime_seconds": round(time.time() - _START_TIME),
        "version": "1.0.0",
        "config": {
            "model": server.config.OPENAI_CHAT_MODEL,
            "whisper_model": server.config.OPENAI_WHISPER_MODEL,
            "session_ttl": server.config.SESSION_TTL_SECONDS,
            "rag_enabled": kb_chunks > 0,
            "knowledge_chunks": kb_chunks,
        },
        "sessions": session_stats,
        "counters": dict(server.counters),
    })


def handle_dashboard(handler: BaseHTTPRequestHandler, server) -> None:
    #GET —> Minimal HTML dashboard

    session_stats = server.sessions.stats()
    kb_chunks = server.knowledge.chunk_count if server.knowledge else 0
    uptime = round(time.time() - _START_TIME)
    counters = dict(server.counters)

    html = _DASHBOARD_HTML.format(
        uptime=_fmt_uptime(uptime),
        model=server.config.OPENAI_CHAT_MODEL,
        whisper=server.config.OPENAI_WHISPER_MODEL,
        sessions_active=session_stats["active"],
        sessions_total=session_stats["total"],
        rag_chunks=kb_chunks,
        req_total=counters.get("requests_total", 0),
        req_ok=counters.get("requests_ok", 0),
        req_err=counters.get("requests_error", 0),
        req_stop=counters.get("requests_stop", 0),
        port=server.config.PORT,
    )
    send_html(handler, html)


def handle_reload_knowledge(handler: BaseHTTPRequestHandler, server) -> None:
    #POST /admin/reload-knowledge —> reloads the knowledge base

    auth = handler.headers.get("Authorization", "")
    if auth != server.config.AUTH_TOKEN:
        send_json(handler, {"error": "Unauthorized"}, 401)
        return
    n = server.knowledge.reload()
    send_json(handler, {"status": "ok", "chunks_loaded": n})


def _fmt_uptime(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


#dashboard HTML
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAO API — Dashboard</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --accent: #58a6ff; --green: #3fb950; --red: #f85149;
    --yellow: #d29922; --text: #e6edf3; --muted: #8b949e;
    --font: 'Segoe UI', system-ui, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: var(--font);
          min-height: 100vh; padding: 2rem; }}
  h1 {{ font-size: 1.6rem; color: var(--accent); margin-bottom: 0.25rem; }}
  .subtitle {{ color: var(--muted); font-size: 0.875rem; margin-bottom: 2rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
           gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-radius: 8px; padding: 1.25rem; }}
  .card-label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: .05em;
                 color: var(--muted); margin-bottom: 0.5rem; }}
  .card-value {{ font-size: 1.75rem; font-weight: 700; color: var(--text); }}
  .card-value.green {{ color: var(--green); }}
  .card-value.red {{ color: var(--red); }}
  .card-value.accent {{ color: var(--accent); }}
  .section {{ background: var(--surface); border: 1px solid var(--border);
              border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }}
  .section h2 {{ font-size: 1rem; color: var(--accent); margin-bottom: 1rem;
                 border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
  .kv {{ display: flex; justify-content: space-between; padding: 0.4rem 0;
         border-bottom: 1px solid #21262d; font-size: 0.875rem; }}
  .kv:last-child {{ border-bottom: none; }}
  .kv-key {{ color: var(--muted); }}
  .kv-val {{ color: var(--text); font-family: monospace; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 0.75rem; font-weight: 600; }}
  .badge.ok {{ background: #1a3a1a; color: var(--green); border: 1px solid var(--green); }}
  .badge.warn {{ background: #3a2a0a; color: var(--yellow); border: 1px solid var(--yellow); }}
  code {{ background: #21262d; border-radius: 4px; padding: 2px 6px;
          font-family: monospace; font-size: 0.85em; color: var(--accent); }}
  .endpoint {{ background: #21262d; border-radius: 6px; padding: 1rem;
               font-family: monospace; font-size: 0.8rem; word-break: break-all;
               color: #c9d1d9; border-left: 3px solid var(--accent); }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.75rem;
            margin-top: 2rem; }}
  .refresh {{ float: right; font-size: 0.75rem; color: var(--muted); cursor: pointer;
              background: none; border: 1px solid var(--border); border-radius: 4px;
              padding: 4px 10px; color: var(--accent); }}
  .refresh:hover {{ background: var(--border); }}
</style>
</head>
<body>
<h1>🤖 NAO ↔ ChatGPT API</h1>
<p class="subtitle">Bridge server running — uptime: <strong>{uptime}</strong></p>

<div class="grid">
  <div class="card">
    <div class="card-label">Total Requests</div>
    <div class="card-value accent">{req_total}</div>
  </div>
  <div class="card">
    <div class="card-label">Successful Replies</div>
    <div class="card-value green">{req_ok}</div>
  </div>
  <div class="card">
    <div class="card-label">Errors</div>
    <div class="card-value red">{req_err}</div>
  </div>
  <div class="card">
    <div class="card-label">Active Sessions</div>
    <div class="card-value accent">{sessions_active}</div>
  </div>
  <div class="card">
    <div class="card-label">RAG Chunks</div>
    <div class="card-value accent">{rag_chunks}</div>
  </div>
  <div class="card">
    <div class="card-label">STOP Commands</div>
    <div class="card-value">{req_stop}</div>
  </div>
</div>

<div class="section">
  <h2>⚙️ Configuration</h2>
  <div class="kv"><span class="kv-key">Chat Model</span><span class="kv-val"><code>{model}</code></span></div>
  <div class="kv"><span class="kv-key">Whisper Model</span><span class="kv-val"><code>{whisper}</code></span></div>
  <div class="kv"><span class="kv-key">Sessions (total)</span><span class="kv-val">{sessions_total}</span></div>
  <div class="kv"><span class="kv-key">RAG</span>
    <span class="kv-val">
      <span class="badge" id="rag-badge">{rag_chunks} chunks</span>
    </span>
  </div>
  <div class="kv"><span class="kv-key">Status</span>
    <span class="kv-val"><span class="badge ok">ONLINE</span></span>
  </div>
</div>

<div class="section">
  <h2>NAO Endpoint</h2>
  <div class="endpoint">POST http://&lt;SERVER_IP&gt;:{port}/speech/id/{{chat-id}}/culture/en-GB/raw/false/persona/{{persona}}/responselength/{{short|medium|standard}}/ai-version/gpt-4o</div>
  <br>
  <div class="kv"><span class="kv-key">Health Check</span><span class="kv-val"><code>GET /health</code></span></div>
  <div class="kv"><span class="kv-key">JSON Metrics</span><span class="kv-val"><code>GET /status</code></span></div>
  <div class="kv"><span class="kv-key">Reload RAG</span><span class="kv-val"><code>POST /admin/reload-knowledge</code></span></div>
</div>

<div class="section">
  <h2>RAG — Knowledge Base</h2>
  <p style="color:var(--muted);font-size:.875rem">
    Add <code>.txt</code> or <code>.md</code> files to <code>data/knowledge/</code>
    and call <code>POST /admin/reload-knowledge</code> to reindex.
  </p>
</div>

<button class="refresh" onclick="location.reload()">↻ Refresh</button>
<footer>NAO API v1.0 — Python stdlib · OpenAI · Zero external dependencies</footer>
</body>
</html>"""
