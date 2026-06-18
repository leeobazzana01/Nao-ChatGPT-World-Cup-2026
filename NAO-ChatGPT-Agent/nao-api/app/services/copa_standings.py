#services/copa_standings.py —> computes group tables from finished matches
#points: win=3 draw=1 loss=0; tie-break: points, goal diff, goals for.

from datetime import datetime
from app.services.copa_data import GROUPS, FIXTURES, BR_TZ


class _Row:
    #single team line inside a group table
    __slots__ = ("team", "p", "w", "d", "l", "gf", "ga")

    def __init__(self, team: str):
        self.team = team
        self.p = self.w = self.d = self.l = self.gf = self.ga = 0

    @property
    def pts(self) -> int:
        return self.w * 3 + self.d

    @property
    def gd(self) -> int:
        return self.gf - self.ga

    def add(self, scored: int, conceded: int) -> None:
        #register one finished match for this team
        self.p += 1
        self.gf += scored
        self.ga += conceded
        if scored > conceded:
            self.w += 1
        elif scored == conceded:
            self.d += 1
        else:
            self.l += 1


def compute_group(group: str, now: datetime | None = None) -> list[_Row]:
    #build a sorted standings table for one group using only scored matches
    now = now or datetime.now(BR_TZ)
    rows = {team: _Row(team) for team in GROUPS[group]}

    for m in FIXTURES:
        if m.group != group or not m.has_score:
            continue
        rows[m.home].add(m.home_score, m.away_score)
        rows[m.away].add(m.away_score, m.home_score)

    table = list(rows.values())
    #sort by points, then goal diff, then goals for, then name
    table.sort(key=lambda r: (r.pts, r.gd, r.gf, r.team), reverse=True)
    return table


def render_group(group: str) -> str:
    #plain-text table -> one line per team, RAG-friendly (no markdown)
    #group label repeated per line so TF-IDF can tell groups apart
    table = compute_group(group)
    lines = [f"Classificação do Grupo {group} da Copa do Mundo 2026 (Grupo {group}):"]
    for pos, r in enumerate(table, 1):
        lines.append(
            f"Grupo {group}, {pos}º lugar: {r.team}, {r.pts} pontos, {r.p} jogos, "
            f"{r.w} vitórias, {r.d} empates, {r.l} derrotas, "
            f"{r.gf} gols pró, {r.ga} gols contra, saldo {r.gd:+d}."
        )
    return "\n".join(lines)


def render_all_groups() -> str:
    #full standings block; blank line between groups -> one chunk per group
    return "\n\n".join(render_group(g) for g in GROUPS)
