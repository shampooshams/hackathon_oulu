"""Fact store: every number the AI is allowed to say, each with an ID and source.

The LLM must cite fact IDs like [F3]; verify.py checks that every number it
writes matches a cited fact. Fact IDs become the 'fact receipts' in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from companion.config import LEAGUE
from companion.data.providers import Snapshot
from companion.scenarios import ScenarioResult
from companion.stats import (fmt_date, game_line, head_to_head, next_game, ordinal, scorers,
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
    fs.add("format", "Playoff format",
           f"Top {LEAGUE.direct_spots} go straight to the quarter-finals; {LEAGUE.direct_spots + 1}th–"
           f"{LEAGUE.playin_last}th play a play-in round; {LEAGUE.playin_last + 1}th–{len(rows)}th miss the playoffs",
           "Liiga regular-season rules")
    fs.add("rank", f"{T} league position", ordinal(row.rank), src_calc)
    fs.add("points", f"{T} points", row.pts, src_calc)
    fs.add("gp", f"{T} games played", row.gp, src_calc)
    fs.add("record", f"{T} record (W–OTW–OTL–L)", f"{row.w}–{row.otw}–{row.otl}–{row.l}", src_calc)
    fs.add("goals", f"{T} goals for–against", f"{row.gf}–{row.ga}", src_calc)
    fs.add("gd", f"{T} goal difference", f"{row.gd:+d}", src_calc)

    results = team_results(snap, team)
    if results:
        last5 = results[-5:]
        fs.add("form5", f"{T} last {len(last5)} results (oldest→newest)",
               ", ".join(r["outcome"] for r in last5), src_data)
        fs.add("form5_pts", f"{T} points from last {len(last5)} games", sum(r["points"] for r in last5), src_calc)
        kind, n = streak(results)
        streak_txt = (("won the last game" if kind == "win" else "lost the last game") if n == 1
                      else f"{n} {'wins' if kind == 'win' else 'losses'} in a row")
        fs.add("streak", f"{T} current streak (OT results count as wins/losses)", streak_txt, src_calc)
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
            fs.add("h2h", f"{T} vs {O} this season",
                   f"{w} win{'s' if w != 1 else ''}, {len(h2h) - w} loss{'es' if len(h2h) - w != 1 else ''} "
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

    remaining = sum(1 for x in snap.games if x["status"] != "final" and team in (x["home"], x["away"]))
    fs.add("remaining", f"{T} regular-season games left", remaining, f"{snap.source} · fixtures")

    if scen:
        fs.add("p_top6", f"{T} chance of a top-{LEAGUE.direct_spots} finish (direct quarter-final)",
               pct(scen.p_top6[team]), src_sim)
        fs.add("p_playin", f"{T} chance of finishing {LEAGUE.direct_spots + 1}th–{LEAGUE.playin_last}th (play-in)",
               pct(scen.p_playin[team]), src_sim)
        fs.add("p_top10", f"{T} chance of reaching the playoffs incl. play-in (top {LEAGUE.playin_last})",
               pct(scen.p_top10[team]), src_sim)
        fs.add("p_out", f"{T} chance of missing the playoffs", pct(scen.p_out[team]), src_sim)
        fs.add("p_first", f"{T} chance of finishing 1st", pct(scen.p_first[team]), src_sim)
        fs.add("proj_points", f"{T} projected final points (median)", round(scen.proj_points[team]), src_sim)
        fs.add("cutline", f"Projected final points of the {ordinal(LEAGUE.direct_spots)}-placed team (median)",
               f"{round(scen.cutline_median)} pts", src_sim)
        st = scen.stakes.get(team)
        if st:
            fs.add("p_win_next", f"Model's win probability for {T} next game (not betting odds)",
                   pct(st["p_win"]), src_sim)
            fs.add("stake_win", f"{T} top-{LEAGUE.direct_spots} chance if they win the next game",
                   pct(st["top6_if_win"]), src_sim)
            fs.add("stake_loss", f"{T} top-{LEAGUE.direct_spots} chance if they lose the next game (incl. OT/SO)",
                   pct(st["top6_if_loss"]), src_sim)
            swing = round(100 * st["top6_if_win"]) - round(100 * st["top6_if_loss"])
            fs.add("stake_swing", f"Swing in {T} top-{LEAGUE.direct_spots} chance riding on the next game",
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
