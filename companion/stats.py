"""Deterministic stats computed from results. No AI here: these are the facts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from companion.config import LEAGUE
from companion.data.providers import Snapshot


@dataclass
class Row:
    team: str
    name: str
    gp: int = 0
    w: int = 0
    otw: int = 0
    otl: int = 0
    d: int = 0          # draws (football)
    l: int = 0
    gf: int = 0
    ga: int = 0
    pts: int = 0
    rank: int = 0

    @property
    def gd(self) -> int:
        return self.gf - self.ga


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%a ") + str(d.day) + d.strftime(" %b")


def finals(snap: Snapshot) -> list[dict]:
    return sorted((g for g in snap.games if g["status"] == "final"), key=lambda g: (g["date"], g["id"]))


def result_for(g: dict, team: str) -> dict:
    home = g["home"] == team
    gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
    won, extra = gf > ga, g["decided"] in ("OT", "SO")
    if gf == ga:
        outcome = "D"
    else:
        outcome = ("OTW" if extra else "W") if won else ("OTL" if extra else "L")
    pts = {"W": LEAGUE.points_reg_win, "OTW": LEAGUE.points_ot_win, "OTL": LEAGUE.points_ot_loss,
           "D": LEAGUE.points_draw, "L": 0}[outcome]
    return {"game": g, "home": home, "opponent": g["away"] if home else g["home"],
            "gf": gf, "ga": ga, "outcome": outcome, "points": pts, "won": won}


def standings(snap: Snapshot) -> list[Row]:
    rows = {t: Row(t, snap.name(t)) for t in snap.teams}
    for g in finals(snap):
        for t in (g["home"], g["away"]):
            r, res = rows[t], result_for(g, t)
            r.gp += 1
            r.gf += res["gf"]
            r.ga += res["ga"]
            r.pts += res["points"]
            setattr(r, res["outcome"].lower(), getattr(r, res["outcome"].lower()) + 1)
    # Liiga tie-break: points, then regulation (3-point) wins, then goal difference, then goals scored.
    # Football: points, goal difference, goals scored.
    reg = LEAGUE.tiebreak_reg_wins
    ordered = sorted(rows.values(), key=lambda r: (-r.pts, -r.w if reg else 0, -r.gd, -r.gf, r.name))
    for i, r in enumerate(ordered, 1):
        r.rank = i
    return ordered


def team_results(snap: Snapshot, team: str) -> list[dict]:
    return [result_for(g, team) for g in finals(snap) if team in (g["home"], g["away"])]


def streak(results: list[dict]) -> tuple[str, int]:
    """('win'|'draw'|'loss', length) counting OT results by win/loss."""
    if not results:
        return "none", 0

    def kind(r):
        return "draw" if r["outcome"] == "D" else ("win" if r["won"] else "loss")
    k, n = kind(results[-1]), 0
    for r in reversed(results):
        if kind(r) != k:
            break
        n += 1
    return k, n


def next_game(snap: Snapshot, team: str) -> dict | None:
    upcoming = sorted((g for g in snap.games if g["status"] != "final" and team in (g["home"], g["away"])),
                      key=lambda g: (g["date"], g["id"]))
    return upcoming[0] if upcoming else None


def head_to_head(snap: Snapshot, team: str, opp: str) -> list[dict]:
    return [r for r in team_results(snap, team) if r["opponent"] == opp]


def scorers(snap: Snapshot, team: str) -> list[dict]:
    tally: dict[str, dict] = {}
    for evs in snap.events.values():
        for e in evs:
            if e["type"] != "goal" or e.get("team") != team or e.get("period") == "SO":
                continue
            tally.setdefault(e["player"], {"name": e["player"], "g": 0, "a": 0})["g"] += 1
            for a in e.get("assists", []):
                tally.setdefault(a, {"name": a, "g": 0, "a": 0})["a"] += 1
    out = list(tally.values())
    for p in out:
        p["pts"] = p["g"] + p["a"]
    return out


def league_scorers(snap: Snapshot) -> list[dict]:
    """Top goalscorers across the league: [{name, team, g}], most goals first."""
    tally: dict[tuple, int] = {}
    for evs in snap.events.values():
        for e in evs:
            if e["type"] == "goal" and e.get("player") and e.get("period") != "SO":
                tally[(e["player"], e["team"])] = tally.get((e["player"], e["team"]), 0) + 1
    return [{"name": n, "team": t, "g": g} for (n, t), g in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]


def game_line(snap: Snapshot, g: dict) -> str:
    extra = f" ({g['decided']})" if g["decided"] in ("OT", "SO") else ""
    return (f"{snap.name(g['home'])} {g['home_goals']}–{g['away_goals']} "
            f"{snap.name(g['away'])}{extra}, {fmt_date(g['date'])}")
