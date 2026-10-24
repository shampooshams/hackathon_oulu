"""Game Night: play tonight's game event by event, then update the season picture.

Tonight's game is simulated from team strengths (real data or mock alike).
The event shapes match the API's feed, so a live feed can replace the simulation later.
"""
from __future__ import annotations

import copy

import numpy as np

from companion.config import LEAGUE
from companion.data.events_gen import generate_events, simulate_result
from companion.data.providers import Snapshot
from companion.facts import FactStore, pct
from companion.scenarios import ScenarioResult, expected_goals
from companion.stats import game_line, next_game, ordinal, result_for, standings


def simulate_tonight(snap: Snapshot, team: str, seed: int, outcome: str = "any") -> tuple[dict, list[dict]]:
    """Simulate the team's next game. outcome: any | win | loss (for demo control)."""
    g = next_game(snap, team)
    if g is None:
        raise ValueError("No upcoming game")
    lh, la = expected_goals(snap, g["home"], g["away"])
    for s in range(seed, seed + 500):
        rng = np.random.default_rng(s)
        hg, ag, dec = simulate_result(lh, la, rng)
        game = {**g, "status": "final", "home_goals": hg, "away_goals": ag, "decided": dec}
        won = result_for(game, team)["won"]
        if outcome == "any" or (outcome == "win") == won:
            return game, generate_events(game, snap.roster(g["home"]), snap.roster(g["away"]), rng)
    raise RuntimeError("Could not find a matching simulated outcome")


def apply_result(snap: Snapshot, game: dict, events: list[dict]) -> Snapshot:
    new = copy.copy(snap)
    new.games = [game if x["id"] == game["id"] else x for x in snap.games]
    new.events = {**snap.events, game["id"]: events}
    return new


def event_facts(snap: Snapshot, game: dict, ev: dict) -> FactStore:
    fs = FactStore(prefix="E")
    H, A = snap.name(game["home"]), snap.name(game["away"])
    fs.add("score", "Score now", f"{H} {ev['home_score']}–{ev['away_score']} {A}", "Live event feed")
    if ev.get("period") is not None:
        names = LEAGUE.period_names
        per = {"OT": "overtime", "SO": "shootout"}.get(
            ev["period"], names[ev["period"] - 1] if isinstance(ev["period"], int) and ev["period"] <= len(names)
            else f"period {ev['period']}")
        fs.add("time", "Game time", f"{per}, {ev['clock']}" if ev.get("clock") else per, "Live event feed")
    if ev.get("team"):
        fs.add("ev_team", "Team", snap.name(ev["team"]), "Live event feed")
    if ev.get("player"):
        fs.add("player", "Player", ev["player"], "Live event feed")
    if ev.get("assists"):
        fs.add("assists", "Assists", ", ".join(ev["assists"]), "Live event feed")
    if ev.get("detail"):
        fs.add("detail", "Detail", ev["detail"], "Live event feed")
    return fs


def postgame_facts(before: Snapshot, after: Snapshot, team: str, game: dict,
                   scen_before: ScenarioResult, scen_after: ScenarioResult,
                   profile: dict | None) -> tuple[FactStore, list[str]]:
    fs = FactStore(prefix="P")
    T = after.name(team)
    res = result_for(game, team)
    rb = next(r for r in standings(before) if r.team == team)
    rows_after = standings(after)
    ra = next(r for r in rows_after if r.team == team)
    src_live, src_calc = "Live event feed", f"Computed from {after.source} results incl. tonight"
    src_sim = f"Season simulation · {scen_after.n:,} runs"

    fs.add("final", "Final score", game_line(after, game), src_live)
    reg = "" if LEAGUE.draws or LEAGUE.points_ot_win == LEAGUE.points_reg_win else " in regulation"
    fs.add("result", f"{T} result", {"W": f"win{reg}", "OTW": "win in overtime/shootout", "D": "draw",
                                      "OTL": "loss in overtime/shootout", "L": f"loss{reg}"}[res["outcome"]],
           src_live)
    fs.add("points_earned", f"Points {T} earned tonight", res["points"], src_calc)
    fs.add("points_after", f"{T} points now", ra.pts, src_calc)
    fs.add("rank_before", f"{T} position before tonight", ordinal(rb.rank), src_calc)
    fs.add("rank_after", f"{T} position now (other games tonight still to finish)", ordinal(ra.rank), src_calc)
    b, a = scen_before.p_top6[team], scen_after.p_top6[team]
    fs.add("top6_before", f"{T} top-{LEAGUE.direct_spots} chance before the game", pct(b), src_sim)
    fs.add("top6_after", f"{T} top-{LEAGUE.direct_spots} chance now", pct(a), src_sim)
    ch = round(100 * a) - round(100 * b)
    fs.add("top6_change", f"Change in {T} top-{LEAGUE.direct_spots} chance",
           f"{'up' if ch > 0 else 'down' if ch < 0 else 'unchanged,'} {abs(ch)} percentage point{'' if abs(ch) == 1 else 's'}",
           src_sim)
    fs.add("top10_after", f"{T} chance of reaching the playoffs (top {LEAGUE.playin_last}) now", pct(scen_after.p_top10[team]),
           src_sim)

    goals = {}
    for e in after.events.get(game["id"], []):
        if e["type"] == "goal" and e["team"] == team and e["period"] != "SO":
            goals[e["player"]] = goals.get(e["player"], 0) + 1
    if goals:
        star, n = max(goals.items(), key=lambda kv: kv[1])
        fs.add("star", f"{T} top scorer tonight{' (fictional mock player)' if after.is_mock else ''}",
               f"{star}, {n} goal{'s' if n > 1 else ''}", src_live)

    alerts = []
    if profile:
        pred = (profile.get("predictions") or {}).get(game["id"])
        if pred:
            ph, pa = pred["home"], pred["away"]
            exact = (ph, pa) == (game["home_goals"], game["away_goals"])
            right_winner = (ph > pa) == (game["home_goals"] > game["away_goals"]) and ph != pa
            fs.add("prediction", "User's prediction",
                   f"{after.name(game['home'])} {ph}–{pa} {after.name(game['away'])}", "Your profile")
            fs.add("prediction_verdict", "How the prediction did",
                   "exact score, spot on" if exact else ("right winner, wrong score" if right_winner else "missed it"),
                   "Computed")
        al = profile.get("alerts") or {}
        if al.get("top6_drop") and rb.rank <= LEAGUE.direct_spots < ra.rank:
            alerts.append(f"🔔 Alert: {T} have dropped out of the top {LEAGUE.direct_spots}, now "
                          f"{fs.v('rank_after')} {fs.c('rank_after')}.")
        th = al.get("odds_below")
        if th and round(100 * a) < th <= round(100 * b):
            alerts.append(f"🔔 Alert: {T}'s top-{LEAGUE.direct_spots} chance fell below your threshold, now "
                          f"{fs.v('top6_after')} {fs.c('top6_after')}.")
    return fs, alerts
