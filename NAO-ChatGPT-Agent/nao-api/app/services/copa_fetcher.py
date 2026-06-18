#services/copa_fetcher.py —> resolves match results.
#two jobs:
#  get_final(match)  -> final score for the scheduler (dict first, HTTP second)
#  fetch_live(match) -> real-time score for the GET /copa/live path (HTTP first)
#HTTP is OPTIONAL: if COPA_LIVE_SOURCE_URL is empty we stay fully offline and
#only use the static dictionary, so nothing breaks without internet.

import json
import ssl
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional
from app.services.copa_data import Match, BR_TZ, _norm
from app.utils import logger as log_module

_log = log_module.get("copa_fetcher")


class LiveResult:
    #normalized live snapshot returned to the route / chat layer
    __slots__ = ("found", "status", "home", "away",
                 "home_score", "away_score", "kickoff", "note", "source")

    def __init__(self, found, status, home, away,
                 home_score=None, away_score=None, kickoff=None, note="", source="dict"):
        self.found = found
        self.status = status            # "finished" | "live" | "scheduled" | "unknown"
        self.home = home
        self.away = away
        self.home_score = home_score
        self.away_score = away_score
        self.kickoff = kickoff
        self.note = note
        self.source = source            # "http" | "dict"

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "status": self.status,
            "home": self.home,
            "away": self.away,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "kickoff": self.kickoff.isoformat() if self.kickoff else None,
            "note": self.note,
            "source": self.source,
        }

    def speakable(self) -> str:
        #short natural-language line the persona can read aloud
        if not self.found:
            return "Não encontrei esse jogo na tabela da Copa."
        if self.status == "finished":
            return f"O jogo terminou: {self.home} {self.home_score} a {self.away_score} {self.away}."
        if self.status == "live":
            if self.home_score is None:
                return (f"O jogo entre {self.home} e {self.away} está rolando agora, "
                        f"mas não consegui o placar ao vivo neste momento.")
            return (f"Agora, ao vivo: {self.home} {self.home_score} a "
                    f"{self.away_score} {self.away}.")
        if self.status == "scheduled":
            return f"O jogo entre {self.home} e {self.away} ainda não começou."
        return f"Não tenho o placar de {self.home} contra {self.away} agora."


class CopaFetcher:
    def __init__(self, live_source_url: str = "", timeout: int = 8) -> None:
        self._url = live_source_url.strip()
        self._timeout = timeout

    #scheduler path -> dict is authoritative, HTTP only fills the gaps
    def get_final(self, match: Match) -> Optional[tuple[int, int]]:
        #returns (home_score, away_score) or None if still unknown
        if match.has_score:
            return (match.home_score, match.away_score)

        #dict has no score yet -> try the optional live source
        snap = self._http_lookup(match)
        if snap and snap.status == "finished" and snap.home_score is not None:
            return (snap.home_score, snap.away_score)
        return None

    #GET /copa/live path -> HTTP first, dict as fallback
    def fetch_live(self, match: Optional[Match], now: Optional[datetime] = None) -> LiveResult:
        now = now or datetime.now(BR_TZ)
        if match is None:
            return LiveResult(False, "unknown", None, None,
                              note="Jogo não localizado na tabela.")

        #1) try the real-time HTTP source (only if configured)
        snap = self._http_lookup(match)
        if snap is not None:
            return snap

        #2) offline fallback -> infer status from the dictionary + clock
        if match.has_score:
            return LiveResult(True, "finished", match.home, match.away,
                              match.home_score, match.away_score,
                              match.kickoff, "Placar final (tabela).", "dict")
        if match.is_live(now):
            return LiveResult(True, "live", match.home, match.away,
                              None, None, match.kickoff,
                              "Sem feed ao vivo configurado.", "dict")
        if now < match.kickoff:
            return LiveResult(True, "scheduled", match.home, match.away,
                              None, None, match.kickoff,
                              "Partida ainda não começou.", "dict")
        return LiveResult(True, "finished", match.home, match.away,
                          None, None, match.kickoff,
                          "Partida encerrada, placar ainda não publicado.", "dict")

    #internal HTTP lookup -> returns None on any failure (silent fallback)
    def _http_lookup(self, match: Match) -> Optional[LiveResult]:
        if not self._url:
            return None
        try:
            #the real source is expected to accept ?home=&away= and return JSON
            #{"status": "...", "home_score": int, "away_score": int}
            qs = f"?home={urllib.parse.quote(match.home)}&away={urllib.parse.quote(match.away)}"
            req = urllib.request.Request(self._url + qs, headers={"User-Agent": "nao-api/1.0"})
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=self._timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return LiveResult(
                found=True,
                status=data.get("status", "unknown"),
                home=match.home, away=match.away,
                home_score=data.get("home_score"),
                away_score=data.get("away_score"),
                kickoff=match.kickoff,
                note="Dados ao vivo.", source="http",
            )
        except Exception as exc:
            _log.warning(f"Live HTTP lookup failed ({match.id}): {exc}")
            return None


#urllib.parse is only needed inside _http_lookup; import lazily to keep top clean
import urllib.parse  # noqa: E402
