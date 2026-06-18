#services/copa_data.py —> static fixture dictionary for FIFA World Cup 2026
#this is the "scraping dictionary": every group-stage match with its
#kickoff time in BRASILIA time and the known final score (None if not played).
#the scheduler and the live fetcher both read from here as the source of truth.

import re
import unicodedata
from datetime import datetime, timezone, timedelta

#brasilia timezone (UTC-3, no DST since 2019)
BR_TZ = timezone(timedelta(hours=-3))

#how long after kickoff a match is considered finished (90' + stoppage + halftime)
MATCH_DURATION_MINUTES = 120

#teams per group (used for standings and live lookup)
GROUPS: dict[str, list[str]] = {
    "A": ["México", "África do Sul", "Coreia do Sul", "Tchéquia"],
    "B": ["Canadá", "Bósnia e Herzegovina", "Catar", "Suíça"],
    "C": ["Brasil", "Marrocos", "Haiti", "Escócia"],
    "D": ["Estados Unidos", "Paraguai", "Austrália", "Turquia"],
    "E": ["Alemanha", "Curaçau", "Costa do Marfim", "Equador"],
    "F": ["Holanda", "Japão", "Suécia", "Tunísia"],
    "G": ["Bélgica", "Egito", "Irã", "Nova Zelândia"],
    "H": ["Espanha", "Cabo Verde", "Arábia Saudita", "Uruguai"],
    "I": ["França", "Senegal", "Iraque", "Noruega"],
    "J": ["Argentina", "Argélia", "Áustria", "Jordânia"],
    "K": ["Portugal", "República Democrática do Congo", "Uzbequistão", "Colômbia"],
    "L": ["Inglaterra", "Croácia", "Gana", "Panamá"],
}

#alias map -> lets live detection match casual / foreign spellings to canonical names
TEAM_ALIASES: dict[str, str] = {
    "eua": "Estados Unidos", "estados unidos": "Estados Unidos", "usa": "Estados Unidos",
    "estados unidos da america": "Estados Unidos",
    "coreia": "Coreia do Sul", "coreia do sul": "Coreia do Sul",
    "republica da coreia": "Coreia do Sul", "korea": "Coreia do Sul",
    "catar": "Catar", "qatar": "Catar",
    "canada": "Canadá",
    "bosnia": "Bósnia e Herzegovina", "bosnia e herzegovina": "Bósnia e Herzegovina",
    "rd congo": "República Democrática do Congo",
    "republica democratica do congo": "República Democrática do Congo",
    "congo": "República Democrática do Congo",
    "africa do sul": "África do Sul",
    "costa do marfim": "Costa do Marfim",
    "nova zelandia": "Nova Zelândia",
    "arabia saudita": "Arábia Saudita",
    "ira": "Irã", "iran": "Irã",
}

#raw fixture table -> (round, group, "YYYY-MM-DD HH:MM" Brasilia, home, away, home_score, away_score, city)
#scores are None when the match had not been played at data-capture time.
_TABLE: list[tuple] = [
    #--- 1st round ---
    (1, "A", "2026-06-11 16:00", "México", "África do Sul", 2, 0, "Cidade do México"),
    (1, "A", "2026-06-11 23:00", "Coreia do Sul", "Tchéquia", 2, 1, "Guadalajara"),
    (1, "B", "2026-06-12 16:00", "Canadá", "Bósnia e Herzegovina", 1, 1, "Toronto"),
    (1, "D", "2026-06-12 22:00", "Estados Unidos", "Paraguai", 4, 1, "Los Angeles"),
    (1, "B", "2026-06-13 16:00", "Catar", "Suíça", 1, 1, "Santa Clara"),
    (1, "C", "2026-06-13 19:00", "Brasil", "Marrocos", 1, 1, "Nova York/Nova Jersey"),
    (1, "C", "2026-06-13 22:00", "Haiti", "Escócia", 0, 1, "Boston"),
    (1, "D", "2026-06-14 01:00", "Austrália", "Turquia", 2, 0, "Vancouver"),
    (1, "E", "2026-06-14 14:00", "Alemanha", "Curaçau", 7, 1, "Houston"),
    (1, "F", "2026-06-14 17:00", "Holanda", "Japão", 2, 2, "Dallas"),
    (1, "E", "2026-06-14 20:00", "Costa do Marfim", "Equador", 1, 0, "Filadélfia"),
    (1, "F", "2026-06-14 23:00", "Suécia", "Tunísia", 5, 1, "Monterrey"),
    (1, "H", "2026-06-15 13:00", "Espanha", "Cabo Verde", 0, 0, "Atlanta"),
    (1, "G", "2026-06-15 16:00", "Bélgica", "Egito", 1, 1, "Seattle"),
    (1, "H", "2026-06-15 19:00", "Arábia Saudita", "Uruguai", 1, 1, "Miami"),
    (1, "G", "2026-06-15 22:00", "Irã", "Nova Zelândia", 2, 2, "Los Angeles"),
    (1, "I", "2026-06-16 16:00", "França", "Senegal", 3, 1, "Nova York/Nova Jersey"),
    (1, "I", "2026-06-16 19:00", "Iraque", "Noruega", 1, 4, "Boston"),
    (1, "J", "2026-06-16 22:00", "Argentina", "Argélia", 3, 0, "Kansas City"),
    (1, "J", "2026-06-17 01:00", "Áustria", "Jordânia", 3, 1, "Santa Clara"),
    (1, "K", "2026-06-17 14:00", "Portugal", "República Democrática do Congo", 1, 1, "Houston"),
    (1, "L", "2026-06-17 17:00", "Inglaterra", "Croácia", 4, 2, "Dallas"),
    (1, "L", "2026-06-17 20:00", "Gana", "Panamá", 1, 0, "Toronto"),
    (1, "K", "2026-06-17 23:00", "Uzbequistão", "Colômbia", 1, 3, "Cidade do México"),

    #--- 2nd round ---
    (2, "A", "2026-06-18 13:00", "Tchéquia", "África do Sul", 1, 1, "Atlanta"),
    (2, "B", "2026-06-18 16:00", "Suíça", "Bósnia e Herzegovina", 4, 1, "Los Angeles"),
    (2, "B", "2026-06-18 19:00", "Canadá", "Catar", None, None, "Vancouver"),
    (2, "A", "2026-06-18 22:00", "México", "Coreia do Sul", None, None, "Guadalajara"),
    (2, "D", "2026-06-19 16:00", "Estados Unidos", "Austrália", None, None, "Seattle"),
    (2, "C", "2026-06-19 19:00", "Escócia", "Marrocos", None, None, "Boston"),
    (2, "C", "2026-06-19 21:30", "Brasil", "Haiti", None, None, "Filadélfia"),
    (2, "D", "2026-06-20 00:00", "Turquia", "Paraguai", None, None, "Santa Clara"),
    (2, "F", "2026-06-20 14:00", "Holanda", "Suécia", None, None, "Houston"),
    (2, "E", "2026-06-20 17:00", "Alemanha", "Costa do Marfim", None, None, "Toronto"),
    (2, "E", "2026-06-20 21:00", "Equador", "Curaçau", None, None, "Kansas City"),
    (2, "F", "2026-06-20 23:00", "Tunísia", "Japão", None, None, "Monterrey"),
    (2, "H", "2026-06-21 13:00", "Espanha", "Arábia Saudita", None, None, "Atlanta"),
    (2, "G", "2026-06-21 16:00", "Bélgica", "Irã", None, None, "Los Angeles"),
    (2, "H", "2026-06-21 19:00", "Uruguai", "Cabo Verde", None, None, "Miami"),
    (2, "G", "2026-06-21 22:00", "Nova Zelândia", "Egito", None, None, "Vancouver"),
    (2, "J", "2026-06-22 14:00", "Argentina", "Áustria", None, None, "Dallas"),
    (2, "I", "2026-06-22 18:00", "França", "Iraque", None, None, "Filadélfia"),
    (2, "I", "2026-06-22 21:00", "Noruega", "Senegal", None, None, "Nova York/Nova Jersey"),
    (2, "J", "2026-06-23 00:00", "Jordânia", "Argélia", None, None, "Santa Clara"),
    (2, "K", "2026-06-23 14:00", "Portugal", "Uzbequistão", None, None, "Houston"),
    (2, "L", "2026-06-23 17:00", "Inglaterra", "Gana", None, None, "Boston"),
    (2, "L", "2026-06-23 20:00", "Panamá", "Croácia", None, None, "Toronto"),
    (2, "K", "2026-06-23 23:00", "Colômbia", "República Democrática do Congo", None, None, "Guadalajara"),

    #--- 3rd round ---
    (3, "B", "2026-06-24 16:00", "Suíça", "Canadá", None, None, "Vancouver"),
    (3, "B", "2026-06-24 16:00", "Bósnia e Herzegovina", "Catar", None, None, "Seattle"),
    (3, "C", "2026-06-24 19:00", "Escócia", "Brasil", None, None, "Miami"),
    (3, "C", "2026-06-24 19:00", "Marrocos", "Haiti", None, None, "Atlanta"),
    (3, "A", "2026-06-24 22:00", "Tchéquia", "México", None, None, "Cidade do México"),
    (3, "A", "2026-06-24 22:00", "África do Sul", "Coreia do Sul", None, None, "Monterrey"),
    (3, "E", "2026-06-25 17:00", "Equador", "Alemanha", None, None, "Nova York/Nova Jersey"),
    (3, "E", "2026-06-25 17:00", "Curaçau", "Costa do Marfim", None, None, "Filadélfia"),
    (3, "F", "2026-06-25 20:00", "Japão", "Suécia", None, None, "Dallas"),
    (3, "F", "2026-06-25 20:00", "Tunísia", "Holanda", None, None, "Kansas City"),
    (3, "D", "2026-06-25 23:00", "Turquia", "Estados Unidos", None, None, "Los Angeles"),
    (3, "D", "2026-06-25 23:00", "Paraguai", "Austrália", None, None, "Santa Clara"),
    (3, "I", "2026-06-26 16:00", "Noruega", "França", None, None, "Boston"),
    (3, "I", "2026-06-26 16:00", "Senegal", "Iraque", None, None, "Toronto"),
    (3, "H", "2026-06-26 21:00", "Cabo Verde", "Arábia Saudita", None, None, "Houston"),
    (3, "H", "2026-06-26 21:00", "Uruguai", "Espanha", None, None, "Guadalajara"),
    (3, "G", "2026-06-27 00:00", "Egito", "Irã", None, None, "Seattle"),
    (3, "G", "2026-06-27 00:00", "Nova Zelândia", "Bélgica", None, None, "Vancouver"),
    (3, "L", "2026-06-27 18:00", "Panamá", "Inglaterra", None, None, "Nova York/Nova Jersey"),
    (3, "L", "2026-06-27 18:00", "Croácia", "Gana", None, None, "Filadélfia"),
    (3, "K", "2026-06-27 20:30", "Colômbia", "Portugal", None, None, "Miami"),
    (3, "K", "2026-06-27 20:30", "República Democrática do Congo", "Uzbequistão", None, None, "Atlanta"),
    (3, "J", "2026-06-27 23:00", "Argélia", "Áustria", None, None, "Kansas City"),
    (3, "J", "2026-06-27 23:00", "Jordânia", "Argentina", None, None, "Dallas"),
]


#helpers
def _norm(text: str) -> str:
    #strip accents + lowercase for tolerant matching
    nfkd = unicodedata.normalize("NFKD", text)
    no_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_acc.lower()).strip()


def _make_id(rnd: int, group: str, home: str, away: str) -> str:
    #stable match id -> "R2-B-canada-catar"
    return f"R{rnd}-{group}-{_norm(home).replace(' ', '_')}-{_norm(away).replace(' ', '_')}"


class Match:
    #single fixture; mutable scores so the live fetcher can update them
    __slots__ = ("id", "round", "group", "home", "away",
                 "home_score", "away_score", "kickoff", "city")

    def __init__(self, rnd, group, kickoff_str, home, away, hs, as_, city):
        self.id = _make_id(rnd, group, home, away)
        self.round = rnd
        self.group = group
        self.home = home
        self.away = away
        self.home_score = hs
        self.away_score = as_
        self.kickoff = datetime.strptime(kickoff_str, "%Y-%m-%d %H:%M").replace(tzinfo=BR_TZ)
        self.city = city

    @property
    def finished_at(self):
        #moment the match is assumed over (kickoff + duration)
        return self.kickoff + timedelta(minutes=MATCH_DURATION_MINUTES)

    @property
    def has_score(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    def is_finished(self, now: datetime) -> bool:
        #finished if a score exists OR the duration window already passed
        return self.has_score or now >= self.finished_at

    def is_live(self, now: datetime) -> bool:
        #in-play window and no final score yet
        return self.kickoff <= now < self.finished_at and not self.has_score

    def score_str(self) -> str:
        if not self.has_score:
            return "x"
        return f"{self.home} {self.home_score} x {self.away_score} {self.away}"


#build the fixture list once at import
FIXTURES: list[Match] = [Match(*row) for row in _TABLE]

#all canonical team names (for live detection)
ALL_TEAMS: list[str] = sorted({t for teams in GROUPS.values() for t in teams})


def resolve_team(token: str) -> str | None:
    #map a free-text token to a canonical team name (alias-aware)
    n = _norm(token)
    if n in TEAM_ALIASES:
        return TEAM_ALIASES[n]
    for team in ALL_TEAMS:
        if _norm(team) == n:
            return team
    return None


def find_teams_in_text(text: str) -> list[str]:
    #return canonical team names mentioned anywhere in the text
    n = _norm(text)
    found: list[str] = []
    #check aliases first (longer keys win to avoid partial overlaps)
    for alias in sorted(TEAM_ALIASES, key=len, reverse=True):
        if alias in n and TEAM_ALIASES[alias] not in found:
            found.append(TEAM_ALIASES[alias])
    for team in ALL_TEAMS:
        if _norm(team) in n and team not in found:
            found.append(team)
    return found


def find_match(team_a: str, team_b: str | None = None) -> Match | None:
    #locate a fixture by one or two team names (most recent kickoff wins)
    cands = [
        m for m in FIXTURES
        if team_a in (m.home, m.away)
        and (team_b is None or team_b in (m.home, m.away))
    ]
    if not cands:
        return None
    cands.sort(key=lambda m: m.kickoff)
    return cands[-1]
