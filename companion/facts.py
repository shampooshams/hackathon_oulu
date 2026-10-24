"""Fact store: every number the AI is allowed to say, each with an ID and source.

The LLM must cite fact IDs like [F3]; verify.py checks that every number it
writes matches a cited fact. Fact IDs become the 'fact receipts' in the UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from companion.config import LEAGUE
from companion.data.providers import Snapshot
from companion.scenarios import ScenarioResult
from companion.stats import (fmt_date, game_line, head_to_head, league_scorers, next_game, ordinal, scorers,
                             standings, streak, team_results)


@dataclass
class Fact:
    id: str
    key: str
    label: str
    display: str
    source: str


@dataclass
class FactStore:
    facts: dict[str, Fact] = field(default_factory=dict)   # id -> Fact
    keys: dict[str, str] = field(default_factory=dict)     # key -> id
    prefix: str = "F"

    def add(self, key: str, label: str, display, source: str) -> Fact:
        fid = f"{self.prefix}{len(self.facts) + 1}"
        f = Fact(fid, key, label, str(display), source)
        self.facts[fid] = f
        self.keys[key] = fid
        return f

    def has(self, key: str) -> bool:
        return key in self.keys

    def get(self, key: str) -> Fact:
        return self.facts[self.keys[key]]

    def v(self, key: str) -> str:
        return self.get(key).display

    def c(self, *keys: str) -> str:
        return "".join(f"[{self.keys[k]}]" for k in keys if k in self.keys)

    def prompt_block(self) -> str:
        return "\n".join(f"{f.id} | {f.label}: {f.display}  (source: {f.source})" for f in self.facts.values())


def stake_race(st: dict) -> tuple[str, float, float]:
    """The race the next game can move: the top places, or the playoff line if the top is out of reach."""
    D, P = LEAGUE.direct_spots, LEAGUE.playin_last
    if P > D and max(st["top6_if_win"], st["top6_if_loss"]) < 0.02:
        return f"top {P}", st["top10_if_win"], st["top10_if_loss"]
    return f"top {D}", st["top6_if_win"], st["top6_if_loss"]


def pct(x: float) -> str:
    p = round(100 * x)
    if p == 0 and x > 0:
        return "<1%"
    if p == 100 and x < 1:
        return ">99%"
    return f"{p}%"


def build_team_facts(snap: Snapshot, team: str, scen: ScenarioResult | None,
                     profile: dict | None = None) -> FactStore:
    fs = FactStore()
    rows = standings(snap)
    row = next(r for r in rows if r.team == team)
    T = snap.name(team)
    asof = fmt_date(snap.as_of)
    src_data = f"{snap.source} · results up to {asof}"
    src_calc = f"Computed from {snap.source} results up to {asof}"
    src_sim = f"Season simulation · {scen.n:,} runs of the remaining fixtures" if scen else ""
    mock_note = " (fictional mock player)" if snap.is_mock else ""

    fs.add("team", "User's favourite team", T, "Your profile")
    D, P = LEAGUE.direct_spots, LEAGUE.playin_last
    middle = f"{D + 1}th–{P}th play the {LEAGUE.first_round}; " if P > D else ""
    fs.add("format", "Season format",
           f"Top {D} go {LEAGUE.direct_goal}; {middle}{P + 1}th–{len(rows)}th {LEAGUE.out_label}",
           f"{LEAGUE.name} rules")
    fs.add("rank", f"{T} league position", ordinal(row.rank), src_calc)
    fs.add("points", f"{T} points", row.pts, src_calc)
    fs.add("gp", f"{T} games played", row.gp, src_calc)
    if LEAGUE.draws:
        fs.add("record", f"{T} record (W–D–L)", f"{row.w}–{row.d}–{row.l}", src_calc)
    elif LEAGUE.points_ot_win == LEAGUE.points_reg_win:   # e.g. basketball: a win is a win
        fs.add("record", f"{T} record (W–L)", f"{row.w + row.otw}–{row.l + row.otl}", src_calc)
    else:
        fs.add("record", f"{T} record (W–OTW–OTL–L)", f"{row.w}–{row.otw}–{row.otl}–{row.l}", src_calc)
    fs.add("goals", f"{T} {LEAGUE.score_word}s for–against", f"{row.gf}–{row.ga}", src_calc)
    fs.add("gd", f"{T} {LEAGUE.score_word} difference", f"{row.gd:+d}", src_calc)

    results = team_results(snap, team)
    if results:
        last5 = results[-5:]
        fs.add("form5", f"{T} last {len(last5)} results (oldest→newest)",
               ", ".join(r["outcome"] for r in last5), src_data)
        fs.add("form5_pts", f"{T} points from last {len(last5)} games", sum(r["points"] for r in last5), src_calc)
        kind, n = streak(results)
        streak_txt = ({"win": "won the last game", "draw": "drew the last game", "loss": "lost the last game"}[kind]
                      if n == 1 else f"{n} {dict(win='wins', draw='draws', loss='losses')[kind]} in a row")
        fs.add("streak", f"{T} current streak" + ("" if LEAGUE.draws else " (OT results count as wins/losses)"),
               streak_txt, src_calc)
        fs.add("last_game", f"{T} last game", game_line(snap, results[-1]["game"]), src_data)

    leader = rows[0]
    fs.add("leader", "League leader", f"{leader.name}, {leader.pts} pts", src_calc)
    ref_row = rows[LEAGUE.direct_spots - 1] if row.rank > LEAGUE.direct_spots else rows[LEAGUE.direct_spots]
    diff = row.pts - ref_row.pts
    where = "behind" if diff < 0 else ("ahead of" if diff > 0 else "level with")
    gap_txt = (f"level on points with {ref_row.name} ({ordinal(ref_row.rank)})" if diff == 0 else
               f"{abs(diff)} pts {where} {ref_row.name} ({ordinal(ref_row.rank)})")
    fs.add("gap6", f"{T} distance to the top-{LEAGUE.direct_spots} line", gap_txt, src_calc)

    g = next_game(snap, team)
    if g:
        home = g["home"] == team
        opp = g["away"] if home else g["home"]
        orow = next(r for r in rows if r.team == opp)
        O = snap.name(opp)
        fs.add("next_game", f"{T} next game",
               f"{'vs' if home else 'at'} {O}, {fmt_date(g['date'])} {g['time']} ({'home' if home else 'away'})",
               f"{snap.source} · fixtures")
        fs.add("opp_rank", f"{O} league position", ordinal(orow.rank), src_calc)
        fs.add("opp_points", f"{O} points", orow.pts, src_calc)
        oresults = team_results(snap, opp)
        if oresults:
            fs.add("opp_form5", f"{O} last {len(oresults[-5:])} results (oldest→newest)",
                   ", ".join(r["outcome"] for r in oresults[-5:]), src_data)
        h2h = head_to_head(snap, team, opp)
        if h2h:
            w = sum(r["won"] for r in h2h)
            d = sum(r["outcome"] == "D" for r in h2h)
            lost = len(h2h) - w - d
            draws = f", {d} draw{'s' if d != 1 else ''}" if LEAGUE.draws else ""
            fs.add("h2h", f"{T} vs {O} this season",
                   f"{w} win{'s' if w != 1 else ''}{draws}, {lost} loss{'es' if lost != 1 else ''} "
                   f"(last: {game_line(snap, h2h[-1]['game'])})", src_data)
        else:
            fs.add("h2h", f"{T} vs {O} this season", "first meeting this season", src_data)

    sc = scorers(snap, team)
    if sc:
        top_g = max(sc, key=lambda p: (p["g"], p["pts"]))
        top_p = max(sc, key=lambda p: (p["pts"], p["g"]))
        fs.add("top_scorer", f"{T} top goalscorer{mock_note}", f"{top_g['name']}, {top_g['g']} goals", src_calc)
        fs.add("top_points", f"{T} points leader{mock_note}",
               f"{top_p['name']}, {top_p['pts']} points ({top_p['g']} goals + {top_p['a']} assists)", src_calc)

    # More context, so the companion can answer follow-ups without guessing
    if results:
        home_r = [r for r in results if r["home"]]
        away_r = [r for r in results if not r["home"]]
        for key, label, rs in (("home_form", "home", home_r), ("away_form", "away", away_r)):
            if rs:
                fs.add(key, f"{T} {label} record this season",
                       f"{sum(r['points'] for r in rs)} points from {len(rs)} {label} games", src_calc)
        fs.add("per_game", f"{T} {LEAGUE.score_word}s per game (for / against)",
               f"{row.gf / row.gp:.1f} / {row.ga / row.gp:.1f}", src_calc)
        fs.add("last5_games", f"{T} last {len(results[-5:])} games (newest first)",
               "; ".join(game_line(snap, r["game"]) for r in reversed(results[-5:])), src_data)
    upcoming = sorted((x for x in snap.games if x["status"] != "final" and team in (x["home"], x["away"])),
                      key=lambda x: (x["date"], x["time"]))[:3]
    if upcoming:
        fs.add("upcoming", f"{T} next {len(upcoming)} games", "; ".join(
            f"{'vs' if x['home'] == team else 'at'} {snap.name(x['away'] if x['home'] == team else x['home'])} "
            f"{fmt_date(x['date'])} {x['time']}" for x in upcoming), f"{snap.source} · fixtures")
    fs.add("table", "League table (position, team, points)",
           ", ".join(f"{ordinal(r.rank)} {r.name} {r.pts}" for r in rows), src_calc)
    league = league_scorers(snap)[:3]
    if league:
        fs.add("league_scorers", f"League top goalscorers{mock_note}",
               "; ".join(f"{p['name']} ({snap.name(p['team'])}) {p['g']} goals" for p in league), src_calc)

    remaining = sum(1 for x in snap.games if x["status"] != "final" and team in (x["home"], x["away"]))
    fs.add("remaining", f"{T} regular-season games left", remaining, f"{snap.source} · fixtures")

    if scen:
        fs.add("p_top6", f"{T} chance of a top-{D} finish ({LEAGUE.direct_goal})", pct(scen.p_top6[team]), src_sim)
        if P > D:
            fs.add("p_playin", f"{T} chance of finishing {D + 1}th–{P}th ({LEAGUE.first_round})",
                   pct(scen.p_playin[team]), src_sim)
            fs.add("p_top10", f"{T} chance to {LEAGUE.reach_goal} (top {P})", pct(scen.p_top10[team]), src_sim)
        fs.add("p_out", f"{T} chance to {LEAGUE.out_label}", pct(scen.p_out[team]), src_sim)
        fs.add("p_first", f"{T} chance of finishing 1st", pct(scen.p_first[team]), src_sim)
        fs.add("proj_points", f"{T} projected final points (median)", round(scen.proj_points[team]), src_sim)
        fs.add("cutline", f"Projected final points of the {ordinal(LEAGUE.direct_spots)}-placed team (median)",
               f"{round(scen.cutline_median)} pts", src_sim)
        st = scen.stakes.get(team)
        if st:
            fs.add("p_win_next", f"Model's win probability for {T} next game (not betting odds)",
                   pct(st["p_win"]), src_sim)
            race, win, loss = stake_race(st)
            fs.add("stake_race", "Race the next game is about", race, src_sim)
            if abs(round(100 * win) - round(100 * loss)) < 1:   # tonight can't move it
                fs.add("stake_flat", f"{T} {race} chance whatever the next game's result "
                       f"({'out of reach' if win < 0.5 else 'almost certain'})", pct(win), src_sim)
            else:
                fs.add("stake_win", f"{T} {race} chance if they win the next game", pct(win), src_sim)
                fs.add("stake_loss", f"{T} {race} chance if they "
                       + ("don't win the next game (draw or loss)" if LEAGUE.draws else
                          "lose the next game (incl. OT/SO)"),
                       pct(loss), src_sim)
                swing = round(100 * win) - round(100 * loss)
                fs.add("stake_swing", f"Swing in {T} {race} chance riding on the next game",
                       f"{swing} percentage point{'' if abs(swing) == 1 else 's'}", src_sim)

    if profile:
        if profile.get("fan_since"):
            fs.add("fan_since", "User has followed the team since", profile["fan_since"], "Your profile")
        if profile.get("fav_player"):
            fs.add("fav_player", "User's favourite player", profile["fav_player"], "Your profile")
        pred = (profile.get("predictions") or {}).get(g["id"]) if g else None
        if pred:
            fs.add("prediction", "User's prediction for the next game",
                   f"{snap.name(g['home'])} {pred['home']}–{pred['away']} {snap.name(g['away'])}", "Your profile")
    return fs


def find_teams(snap: Snapshot, message: str, exclude: str = "") -> list[str]:
    """Teams the fan mentions by name (or id), e.g. "how about Tappara?"."""
    m = message.lower()
    found = []
    for tid, t in snap.teams.items():
        if tid == exclude:
            continue
        names = {t["name"].lower(), tid.lower()}
        if any(re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", m) for n in names if len(n) >= 3):
            found.append(tid)
    return found[:2]


def add_team_facts(fs: FactStore, snap: Snapshot, team: str, other: str, scen: ScenarioResult | None) -> None:
    """Facts about another team the fan asked about, compared with their own team."""
    rows = standings(snap)
    r = next(x for x in rows if x.team == other)
    O, T = snap.name(other), snap.name(team)
    src = f"Computed from {snap.source} results up to {fmt_date(snap.as_of)}"
    k = f"x_{other.lower()}"
    fs.add(f"{k}_rank", f"{O} league position and points", f"{ordinal(r.rank)}, {r.pts} points from {r.gp} games",
           src)
    fs.add(f"{k}_gd", f"{O} {LEAGUE.score_word}s for–against", f"{r.gf}–{r.ga} ({r.gd:+d})", src)
    res = team_results(snap, other)
    if res:
        fs.add(f"{k}_form", f"{O} last {len(res[-5:])} results (oldest→newest)",
               ", ".join(x["outcome"] for x in res[-5:]), src)
    h2h = head_to_head(snap, team, other)
    if h2h:
        w = sum(x["won"] for x in h2h)
        d = sum(x["outcome"] == "D" for x in h2h)
        fs.add(f"{k}_h2h", f"{T} vs {O} this season",
               f"{w} win{'s' if w != 1 else ''}"
               + (f", {d} draw{'s' if d != 1 else ''}" if LEAGUE.draws else "")
               + f", {len(h2h) - w - d} loss{'es' if len(h2h) - w - d != 1 else ''}"
               f" (last: {game_line(snap, h2h[-1]['game'])})", src)
    else:
        fs.add(f"{k}_h2h", f"{T} vs {O} this season", "no meetings yet this season", src)
    if scen:
        fs.add(f"{k}_top", f"{O} chance of a top-{LEAGUE.direct_spots} finish", pct(scen.p_top6[other]),
               f"Season simulation · {scen.n:,} runs")
