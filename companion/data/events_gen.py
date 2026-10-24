"""Generates realistic-looking match results and event feeds.

Used for (1) the mock season and (2) simulating "tonight's game" for the
Game Night demo. Real API events follow the same shape (see DATA_CONTRACT.md).
"""
from __future__ import annotations

import numpy as np

from companion.config import LEAGUE

OFFENCES = ["tripping", "hooking", "high-sticking", "holding", "interference", "slashing", "roughing"]
PERIOD_SECONDS = 1200


def simulate_result(lam_home: float, lam_away: float, rng: np.random.Generator) -> tuple[int, int, str]:
    """Return (home_goals, away_goals, decided) where decided is REG, OT or SO.

    OT/SO winners get +1 goal in the final score (common convention). Football: draws stay draws."""
    hg, ag = int(rng.poisson(lam_home)), int(rng.poisson(lam_away))
    if hg != ag or LEAGUE.draws:
        return hg, ag, "REG"
    decided = "OT" if rng.random() < 0.6 or not LEAGUE.shootout else "SO"
    p_home = 0.5 + 0.15 * (lam_home - lam_away) / max(lam_home + lam_away, 0.1)
    if rng.random() < p_home:
        hg += 1
    else:
        ag += 1
    return hg, ag, decided


def _clock(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _pick(roster: list[dict], rng: np.random.Generator, exclude: set | None = None) -> str:
    pool = [p for p in roster if not exclude or p["name"] not in exclude]
    w = np.array([p["weight"] for p in pool], dtype=float)
    return pool[int(rng.choice(len(pool), p=w / w.sum()))]["name"]


def generate_events(game: dict, roster_home: list[dict], roster_away: list[dict],
                    rng: np.random.Generator) -> list[dict]:
    """Create a chronological event feed consistent with the final score."""
    if LEAGUE.feed == "halves":
        return generate_football_events(game, roster_home, roster_away, rng)
    if LEAGUE.feed == "quarters":
        return generate_quarter_events(game, rng)
    home, away = game["home"], game["away"]
    hg, ag, decided = game["home_goals"], game["away_goals"], game["decided"]
    winner_home = hg > ag
    reg_h, reg_a = hg, ag
    if decided in ("OT", "SO"):
        if winner_home:
            reg_h -= 1
        else:
            reg_a -= 1

    raw = []  # (sort_key, event)
    for team, n, roster in ((home, reg_h, roster_home), (away, reg_a, roster_away)):
        for _ in range(n):
            sec = int(rng.integers(30, 3 * PERIOD_SECONDS - 1))
            raw.append((sec, {"type": "goal", "team": team, "roster": roster}))
    for _ in range(int(rng.poisson(3.5))):
        team = home if rng.random() < 0.5 else away
        sec = int(rng.integers(60, 3 * PERIOD_SECONDS - 1))
        raw.append((sec, {"type": "penalty", "team": team,
                          "roster": roster_home if team == home else roster_away}))
    raw.sort(key=lambda x: x[0])

    events: list[dict] = []
    score = {home: 0, away: 0}
    period_done = 0

    def emit(ev: dict):
        ev["game_id"] = game["id"]
        ev["seq"] = len(events) + 1
        ev["home_score"], ev["away_score"] = score[home], score[away]
        events.append(ev)

    def close_periods(upto: int):
        nonlocal period_done
        while period_done < upto:
            period_done += 1
            emit({"type": "period_end", "period": period_done, "clock": "20:00", "team": None,
                  "player": None, "assists": [], "detail": f"End of period {period_done}"})

    for sec, e in raw:
        period = sec // PERIOD_SECONDS + 1
        close_periods(period - 1)
        clock = _clock(sec % PERIOD_SECONDS)
        if e["type"] == "goal":
            scorer = _pick(e["roster"], rng)
            assists = []
            for _ in range(int(rng.choice([0, 1, 2], p=[0.1, 0.35, 0.55]))):
                assists.append(_pick(e["roster"], rng, exclude={scorer, *assists}))
            score[e["team"]] += 1
            emit({"type": "goal", "period": period, "clock": clock, "team": e["team"],
                  "player": scorer, "assists": assists, "detail": ""})
        else:
            emit({"type": "penalty", "period": period, "clock": clock, "team": e["team"],
                  "player": _pick(e["roster"], rng), "assists": [],
                  "detail": f"2 min, {OFFENCES[int(rng.integers(len(OFFENCES)))]}"})
    close_periods(3)

    win_team = home if winner_home else away
    win_roster = roster_home if winner_home else roster_away
    if decided == "OT":
        sec = int(rng.integers(10, 299))
        score[win_team] += 1
        emit({"type": "goal", "period": "OT", "clock": _clock(sec), "team": win_team,
              "player": _pick(win_roster, rng), "assists": [], "detail": "overtime winner"})
    elif decided == "SO":
        emit({"type": "period_end", "period": "OT", "clock": "05:00", "team": None, "player": None,
              "assists": [], "detail": "Overtime ends scoreless, shootout next"})
        score[win_team] += 1
        emit({"type": "goal", "period": "SO", "clock": "", "team": win_team,
              "player": _pick(win_roster, rng), "assists": [], "detail": "shootout winner"})
    emit({"type": "game_end", "period": None, "clock": "", "team": None, "player": None,
          "assists": [], "detail": f"Final ({decided})" if decided != "REG" else "Final"})
    return events


def generate_football_events(game: dict, roster_home: list[dict], roster_away: list[dict],
                             rng: np.random.Generator) -> list[dict]:
    """Two-half feed (football, bandy): goals with one assist at most, cards (football) or 10-minute
    penalties (bandy), half-time and full time. Clocks are match minutes ("67'"); 'period' is the half."""
    home, away = game["home"], game["away"]
    raw = []
    for team, n, roster in ((home, game["home_goals"], roster_home), (away, game["away_goals"], roster_away)):
        for _ in range(n):
            raw.append((int(rng.integers(1, 91)), "goal", team, roster))
        for _ in range(int(rng.poisson(1.8))):
            raw.append((int(rng.integers(5, 91)), "card", team, roster))
    raw.sort(key=lambda x: x[0])

    events: list[dict] = []
    score = {home: 0, away: 0}
    half_done = False

    def emit(ev: dict):
        ev["game_id"] = game["id"]
        ev["seq"] = len(events) + 1
        ev["home_score"], ev["away_score"] = score[home], score[away]
        events.append(ev)

    def half_time():
        emit({"type": "period_end", "period": 1, "clock": "45'", "team": None, "player": None,
              "assists": [], "detail": "Half-time"})

    for minute, kind, team, roster in raw:
        if minute > 45 and not half_done:
            half_time()
            half_done = True
        period = 1 if minute <= 45 else 2
        if kind == "goal":
            scorer = _pick(roster, rng)
            assists = [_pick(roster, rng, exclude={scorer})] if rng.random() < 0.7 else []
            score[team] += 1
            emit({"type": "goal", "period": period, "clock": f"{minute}'", "team": team,
                  "player": scorer, "assists": assists, "detail": ""})
        elif LEAGUE.discipline == "card":
            emit({"type": "card", "period": period, "clock": f"{minute}'", "team": team,
                  "player": _pick(roster, rng), "assists": [],
                  "detail": "Red card" if rng.random() < 0.06 else "Yellow card"})
        else:
            emit({"type": "penalty", "period": period, "clock": f"{minute}'", "team": team,
                  "player": _pick(roster, rng), "assists": [],
                  "detail": f"{LEAGUE.discipline}, {OFFENCES[int(rng.integers(len(OFFENCES)))]}"})
    if not half_done:
        half_time()
    emit({"type": "game_end", "period": None, "clock": "", "team": None, "player": None,
          "assists": [], "detail": "Full time"})
    return events


def generate_quarter_events(game: dict, rng: np.random.Generator) -> list[dict]:
    """Basketball feed: the score at the end of each quarter (and overtime), then the final.
    Individual baskets aren't simulated, so there are no scorer events."""
    home, away = game["home"], game["away"]
    hg, ag = game["home_goals"], game["away_goals"]
    reg_h, reg_a = hg, ag
    if game["decided"] == "OT":   # level after four quarters; the overtime points make up the rest
        reg_h = reg_a = min(hg, ag) - int(rng.integers(5, 12))

    def split(total: int) -> list[int]:
        w = rng.dirichlet([40, 40, 40, 40])
        parts = [int(x) for x in np.floor(w * total)]
        parts[-1] += total - sum(parts)
        return parts

    qh, qa = split(reg_h), split(reg_a)
    events, sh, sa = [], 0, 0
    for i in range(4):
        sh, sa = sh + qh[i], sa + qa[i]
        events.append({"type": "period_end", "period": i + 1, "clock": "10:00", "team": None, "player": None,
                       "assists": [], "detail": f"End of {LEAGUE.period_names[i]}", "home_score": sh,
                       "away_score": sa})
    if game["decided"] == "OT":
        events.append({"type": "period_end", "period": "OT", "clock": "05:00", "team": None, "player": None,
                       "assists": [], "detail": "End of overtime", "home_score": hg, "away_score": ag})
    events.append({"type": "game_end", "period": None, "clock": "", "team": None, "player": None, "assists": [],
                   "detail": "Final (OT)" if game["decided"] == "OT" else "Final", "home_score": hg,
                   "away_score": ag})
    for i, e in enumerate(events, 1):
        e.update(game_id=game["id"], seq=i)
    return events
