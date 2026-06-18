#utils/responses.py —> helpers to build HTTP responses.

from http.server import BaseHTTPRequestHandler
from typing import Optional


def send_text(handler: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    #sends a plain text response (NAO robot expects to receive)

    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def send_json(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    #sends a JSON response (dashboard and health check)
    
    import json
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def send_html(handler: BaseHTTPRequestHandler, html: str, status: int = 200) -> None:
    #sendding an HTML response

    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    #sendding a JSON error response

    send_json(handler, {"error": message, "status": status}, status)


def send_cors_preflight(handler: BaseHTTPRequestHandler) -> None:
    #responds to OPTIONS for CORS preflight
    
    handler.send_response(204)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    handler.send_header("Content-Length", "0")
    handler.end_headers()
