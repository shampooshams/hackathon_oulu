"""Season simulator: 'what does my team need?'

Plain Monte Carlo over the remaining fixtures. The AI never does this maths;
it only explains the numbers this module produces.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from companion.config import LEAGUE, SIMULATIONS
from companion.data.providers import Snapshot
from companion.stats import finals, next_game, standings

PRIOR_GAMES = 15     # shrink early-season ratings toward league average
RATING_NOISE = 0.10  # per-simulation uncertainty in each team's true strength


@dataclass
class ScenarioResult:
    n: int
    teams: list[str]
    p_top6: dict[str, float]
    p_playin: dict[str, float]
    p_top10: dict[str, float]
    p_out: dict[str, float]
    p_first: dict[str, float]
    proj_points: dict[str, float]
    rank_dist: dict[str, list[float]]          # P(final rank = 1..N)
    cutline_median: float                       # final points of the 6th-placed team
    cutline_range: tuple[float, float]          # 25th-75th percentile
    stakes: dict[str, dict] = field(default_factory=dict)


def ratings(snap: Snapshot) -> tuple[dict, dict, float]:
    games = finals(snap)
    gp = {t: 0 for t in snap.teams}
    gf, ga = dict(gp), dict(gp)
    for g in games:
        for t, f, a in ((g["home"], g["home_goals"], g["away_goals"]),
                        (g["away"], g["away_goals"], g["home_goals"])):
            gp[t] += 1
            gf[t] += f
            ga[t] += a
    total_gp = sum(gp.values())
    avg = (sum(gf.values()) / total_gp) if total_gp else 2.9
    att = {t: (gf[t] + PRIOR_GAMES * avg) / (gp[t] + PRIOR_GAMES) / avg for t in snap.teams}
    dfn = {t: (ga[t] + PRIOR_GAMES * avg) / (gp[t] + PRIOR_GAMES) / avg for t in snap.teams}
    return att, dfn, avg


def expected_goals(snap: Snapshot, home: str, away: str) -> tuple[float, float]:
    att, dfn, avg = ratings(snap)
    return (avg * att[home] * dfn[away] * LEAGUE.home_advantage, avg * att[away] * dfn[home])


def simulate(snap: Snapshot, n: int = SIMULATIONS, seed: int = 7) -> ScenarioResult:
    rng = np.random.default_rng(seed)
    teams = list(snap.teams)
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    rows = {r.team: r for r in standings(snap)}
    pts = np.tile([float(rows[t].pts) for t in teams], (n, 1))
    gd = np.tile([float(rows[t].gd) for t in teams], (n, 1))

    att, dfn, avg = ratings(snap)
    att_s = np.array([att[t] for t in teams]) * np.exp(rng.normal(0, RATING_NOISE, (n, T)))
    dfn_s = np.array([dfn[t] for t in teams]) * np.exp(rng.normal(0, RATING_NOISE, (n, T)))
    nxt = {t: (next_game(snap, t) or {}).get("id") for t in teams}
    won_next: dict[str, np.ndarray] = {}

    remaining = [g for g in snap.games if g["status"] != "final"]
    for g in remaining:
        h, a = idx[g["home"]], idx[g["away"]]
        lh = avg * att_s[:, h] * dfn_s[:, a] * LEAGUE.home_advantage
        la = avg * att_s[:, a] * dfn_s[:, h]
        gh, ga_ = rng.poisson(lh, n), rng.poisson(la, n)
        tie = gh == ga_
        home_ot = rng.random(n) < (0.5 + 0.15 * (lh - la) / (lh + la))
        home_reg, away_reg = gh > ga_, gh < ga_
        pts[:, h] += np.where(home_reg, LEAGUE.points_reg_win,
                              np.where(tie, np.where(home_ot, LEAGUE.points_ot_win, LEAGUE.points_ot_loss), 0))
        pts[:, a] += np.where(away_reg, LEAGUE.points_reg_win,
                              np.where(tie, np.where(home_ot, LEAGUE.points_ot_loss, LEAGUE.points_ot_win), 0))
        margin = (gh - ga_) + np.where(tie, np.where(home_ot, 1, -1), 0)
        gd[:, h] += margin
        gd[:, a] -= margin
        home_won = home_reg | (tie & home_ot)
        if nxt[g["home"]] == g["id"]:
            won_next[g["home"]] = home_won
        if nxt[g["away"]] == g["id"]:
            won_next[g["away"]] = ~home_won

    score = pts * 1000 + gd + rng.random((n, T)) * 0.01
    order = np.argsort(-score, axis=1)
    ranks = np.empty_like(order)
    ranks[np.arange(n)[:, None], order] = np.arange(1, T + 1)

    sixth = np.sort(pts, axis=1)[:, ::-1][:, LEAGUE.direct_spots - 1]
    res = ScenarioResult(
        n=n, teams=teams,
        p_top6={t: float((ranks[:, i] <= LEAGUE.direct_spots).mean()) for t, i in idx.items()},
        p_playin={t: float(((ranks[:, i] > LEAGUE.direct_spots) & (ranks[:, i] <= LEAGUE.playin_last)).mean())
                  for t, i in idx.items()},
        p_top10={t: float((ranks[:, i] <= LEAGUE.playin_last).mean()) for t, i in idx.items()},
        p_out={t: float((ranks[:, i] > LEAGUE.playin_last).mean()) for t, i in idx.items()},
        p_first={t: float((ranks[:, i] == 1).mean()) for t, i in idx.items()},
        proj_points={t: float(np.median(pts[:, i])) for t, i in idx.items()},
        rank_dist={t: [float((ranks[:, i] == r).mean()) for r in range(1, T + 1)] for t, i in idx.items()},
        cutline_median=float(np.median(sixth)),
        cutline_range=(float(np.percentile(sixth, 25)), float(np.percentile(sixth, 75))),
    )
    for t, mask in won_next.items():
        i = idx[t]
        top6 = ranks[:, i] <= LEAGUE.direct_spots
        top10 = ranks[:, i] <= LEAGUE.playin_last
        res.stakes[t] = {
            "game_id": nxt[t],
            "p_win": float(mask.mean()),
            "top6_if_win": float(top6[mask].mean()) if mask.any() else 0.0,
            "top6_if_loss": float(top6[~mask].mean()) if (~mask).any() else 0.0,
            "top10_if_win": float(top10[mask].mean()) if mask.any() else 0.0,
            "top10_if_loss": float(top10[~mask].mean()) if (~mask).any() else 0.0,
        }
    return res
