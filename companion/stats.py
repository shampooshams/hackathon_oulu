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
    outcome = ("OTW" if extra else "W") if won else ("OTL" if extra else "L")
    pts = {"W": LEAGUE.points_reg_win, "OTW": LEAGUE.points_ot_win,
           "OTL": LEAGUE.points_ot_loss, "L": 0}[outcome]
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
    ordered = sorted(rows.values(), key=lambda r: (-r.pts, -r.gd, -r.gf, r.name))
    for i, r in enumerate(ordered, 1):
        r.rank = i
    return ordered


def team_results(snap: Snapshot, team: str) -> list[dict]:
    return [result_for(g, team) for g in finals(snap) if team in (g["home"], g["away"])]


def streak(results: list[dict]) -> tuple[str, int]:
    """('win'|'loss', length) counting OT results by win/loss."""
    if not results:
        return "none", 0
    kind = results[-1]["won"]
    n = 0
    for r in reversed(results):
        if r["won"] != kind:
            break
        n += 1
    return ("win" if kind else "loss"), n


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


def game_line(snap: Snapshot, g: dict) -> str:
    extra = f" ({g['decided']})" if g["decided"] in ("OT", "SO") else ""
    return (f"{snap.name(g['home'])} {g['home_goals']}–{g['away_goals']} "
            f"{snap.name(g['away'])}{extra}, {fmt_date(g['date'])}")
