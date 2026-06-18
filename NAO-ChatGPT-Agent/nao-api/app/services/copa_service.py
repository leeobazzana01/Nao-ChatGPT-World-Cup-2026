#services/copa_service.py —> orchestrates the World Cup feature:
#  - background scheduler that, ~2h after each kickoff, regenerates
#    copa_resultados.txt (results + standings) and reloads the RAG
#  - live-intent detection so the GET/live fetch only fires when the
#    user actually asks for a real-time score
#  - facade used by both the chat layer and the /copa/live route.

import re
import time
import threading
from datetime import datetime
from typing import Optional
from app.services.copa_data import (
    FIXTURES, BR_TZ, find_teams_in_text, find_match, Match,
)
from app.services import copa_standings
from app.services.copa_fetcher import CopaFetcher, LiveResult
from app.utils import logger as log_module

_log = log_module.get("copa")

#name of the RAG file the robot consults for finished matches
RESULTS_FILENAME = "copa_resultados.txt"

#keywords that mean "I want the score RIGHT NOW" -> triggers the GET
_LIVE_PATTERNS = re.compile(
    r"\b(tempo real|ao vivo|agora|neste momento|no momento|"
    r"est[aá] acontecendo|est[aá] rolando|placar atual|"
    r"que horas|live|right now|happening now|current score)\b",
    re.IGNORECASE,
)

#keywords that mean "tell me about a match result" (RAG is enough)
_RESULT_PATTERNS = re.compile(
    r"\b(placar|resultado|quanto|ganhou|venceu|perdeu|empat|"
    r"jogo|partida|gol|classifica|tabela|grupo|score|result)\b",
    re.IGNORECASE,
)


class CopaService:
    def __init__(
        self,
        knowledge,                       # KnowledgeBase (for reload)
        knowledge_dir,                   # pathlib.Path
        live_source_url: str = "",
        tick_seconds: int = 60,
    ) -> None:
        self._knowledge = knowledge
        self._dir = knowledge_dir
        self._tick = tick_seconds
        self._fetcher = CopaFetcher(live_source_url=live_source_url)
        self._last_finished_count = -1
        self._stop = threading.Event()

    #scheduler                                                       
    def start_scheduler(self) -> None:
        #backfill immediately, then watch for matches crossing kickoff+2h
        self._regenerate("startup backfill")
        t = threading.Thread(target=self._loop, daemon=True, name="copa-scheduler")
        t.start()
        _log.info("Copa scheduler started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        #wake every tick; rewrite the RAG file only when a new match finished
        while not self._stop.wait(self._tick):
            try:
                now = datetime.now(BR_TZ)
                finished = [m for m in FIXTURES if m.is_finished(now)]
                if len(finished) != self._last_finished_count:
                    self._regenerate(f"{len(finished)} matches finished")
            except Exception as exc:
                _log.error(f"Copa scheduler error: {exc}")

    def _regenerate(self, reason: str) -> None:
        #pull final scores (dict + optional HTTP), write file, reload RAG
        now = datetime.now(BR_TZ)
        finished = [m for m in FIXTURES if m.is_finished(now)]

        #fill missing scores from the fetcher (no-op offline)
        for m in finished:
            if not m.has_score:
                res = self._fetcher.get_final(m)
                if res:
                    m.home_score, m.away_score = res

        text = self._build_results_text(now)
        path = self._dir / RESULTS_FILENAME
        try:
            path.write_text(text, encoding="utf-8")
            self._last_finished_count = len(finished)
            self._knowledge.reload()
            _log.info(f"copa_resultados.txt updated ({reason}); RAG reloaded")
        except Exception as exc:
            _log.error(f"Failed writing {RESULTS_FILENAME}: {exc}")

    def _build_results_text(self, now: datetime) -> str:
        #RAG-friendly text: finished results grouped by round + full standings
        #blank lines between entries -> chunker isolates each match
        parts = ["# Resultados da Copa do Mundo 2026",
                 f"Atualizado em {now.strftime('%d/%m/%Y %H:%M')} (horário de Brasília)."]

        for rnd in (1, 2, 3):
            done = [m for m in FIXTURES if m.round == rnd and m.has_score]
            if not done:
                continue
            parts.append(f"## Resultados da rodada {rnd}")
            done.sort(key=lambda m: m.kickoff)
            for m in done:
                #repeat team names so TF-IDF retrieves on either team
                parts.append(
                    f"Rodada {rnd}, Grupo {m.group}: {m.home} {m.home_score} x "
                    f"{m.away_score} {m.away}. "
                    f"Resultado de {m.home} contra {m.away}: "
                    f"{m.home} {m.home_score}, {m.away} {m.away_score}, "
                    f"em {m.city}."
                )

        parts.append("## Classificação dos grupos")
        parts.append(copa_standings.render_all_groups())
        #double newline -> each part becomes its own paragraph for the chunker
        return "\n\n".join(parts)

    #live-intent detection (used by chat layer)                     
    def detect_live_query(self, text: str) -> Optional[Match]:
        #return a Match ONLY when the user explicitly asks for a live score
        #and names enough to resolve a fixture -> keeps the GET on demand
        if not text or not _LIVE_PATTERNS.search(text):
            return None
        if not _RESULT_PATTERNS.search(text):
            #"agora" alone (e.g. greetings) must not trigger a fetch
            return None

        teams = find_teams_in_text(text)
        if not teams:
            return None
        if len(teams) >= 2:
            return find_match(teams[0], teams[1])
        return find_match(teams[0])

    def is_result_query(self, text: str) -> bool:
        #true for any past-result/standings question (served by RAG)
        return bool(text and _RESULT_PATTERNS.search(text))

    #live fetch (used by chat layer and /copa/live route)           
    def fetch_live(self, match: Optional[Match]) -> LiveResult:
        return self._fetcher.fetch_live(match)

    def fetch_live_by_text(self, text: str) -> LiveResult:
        #route helper: resolve teams from free text then fetch
        teams = find_teams_in_text(text)
        match = None
        if len(teams) >= 2:
            match = find_match(teams[0], teams[1])
        elif teams:
            match = find_match(teams[0])
        return self._fetcher.fetch_live(match)
