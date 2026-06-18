#routes/copa.py —> GET /copa/live real-time score endpoint.
#fires the live fetch ONLY for this path, so the heavy/real-time lookup
#never runs on ordinary chat turns.

import urllib.parse
from http.server import BaseHTTPRequestHandler
from app.services.copa_data import find_match, find_teams_in_text
from app.utils.responses import send_json, send_error
from app.utils import logger as log_module

_log = log_module.get("copa_route")


def matches(path: str) -> bool:
    return path == "/copa/live"


def handle(handler: BaseHTTPRequestHandler, server) -> None:
    #GET /copa/live?home=Canadá&away=Catar   (or ?q=Canadá e Catar)
    copa = getattr(server, "copa", None)
    if copa is None:
        send_error(handler, "Copa feature not enabled", 503)
        return

    qs = urllib.parse.urlparse(handler.path).query
    params = urllib.parse.parse_qs(qs)
    home = (params.get("home", [""])[0]).strip()
    away = (params.get("away", [""])[0]).strip()
    free = (params.get("q", [""])[0]).strip()

    #resolve a fixture from explicit home/away or from a free-text query
    match = None
    if home and away:
        teams = find_teams_in_text(f"{home} {away}")
        if len(teams) >= 2:
            match = find_match(teams[0], teams[1])
    elif free:
        teams = find_teams_in_text(free)
        if len(teams) >= 2:
            match = find_match(teams[0], teams[1])
        elif teams:
            match = find_match(teams[0])

    if match is None:
        send_error(handler, "Match not found (use ?home=&away= or ?q=)", 404)
        return

    result = copa.fetch_live(match)
    _log.info(f"/copa/live {match.id} -> {result.status} ({result.source})")
    send_json(handler, result.to_dict())
