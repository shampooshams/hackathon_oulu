"""Generate a mock Liiga season (teams, fixtures, results, event feeds).

Team names are real Liiga clubs; ALL players, scores and results are
fictional demo data. Run:  python -m companion.data.generate_mock
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np

from companion.config import AS_OF, LEAGUE, LIIGA, MOCK_DIR, MOCK_FOOTBALL_DIR, VEIKKAUSLIIGA, use_league
from companion.data.events_gen import generate_events, simulate_result

TEAMS = [
    ("KARPAT", "Kärpät", "Oulu"), ("HIFK", "HIFK", "Helsinki"), ("TAPPARA", "Tappara", "Tampere"),
    ("ILVES", "Ilves", "Tampere"), ("TPS", "TPS", "Turku"), ("LUKKO", "Lukko", "Rauma"),
    ("PELICANS", "Pelicans", "Lahti"), ("KALPA", "KalPa", "Kuopio"), ("JYP", "JYP", "Jyväskylä"),
    ("SAIPA", "SaiPa", "Lappeenranta"), ("HPK", "HPK", "Hämeenlinna"), ("ASSAT", "Ässät", "Pori"),
    ("JUKURIT", "Jukurit", "Mikkeli"), ("SPORT", "Sport", "Vaasa"), ("KOOKOO", "KooKoo", "Kouvola"),
    ("KESPOO", "K-Espoo", "Espoo"),
]
FIRST = ["Aleksi", "Eetu", "Joona", "Juho", "Kasper", "Lauri", "Niko", "Oskari", "Otto", "Roope",
         "Santeri", "Valtteri", "Veeti", "Elias", "Arttu", "Henri", "Jesse", "Markus", "Topias",
         "Leo", "Onni", "Eemil", "Akseli", "Ilmari", "Daniel", "Lucas", "Viljami", "Severi"]
LAST = ["Aaltonen", "Heikkinen", "Hiltunen", "Jokela", "Kallio", "Karjalainen", "Koivisto",
        "Lehtinen", "Mäkelä", "Niemi", "Ojala", "Peltola", "Salminen", "Turunen", "Väisänen",
        "Hakala", "Kemppainen", "Lindqvist", "Nyström", "Pesonen", "Saarinen", "Tuominen",
        "Vuorinen", "Keränen", "Huttunen", "Rautio", "Seppälä", "Tolvanen", "Halme", "Ikonen",
        "Laukkanen", "Moilanen", "Pöllänen", "Riikonen", "Sirviö", "Toivonen", "Ylönen", "Ahola"]
SEED = 27
START = date(2026, 9, 12)
DAYS_PER_ROUND = 3
GOALS_PER_TEAM = 2.9


def round_robin(ids: list[str]) -> list[list[tuple[str, str]]]:
    ids = list(ids)
    n = len(ids)
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = ids[i], ids[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        ids = [ids[0], ids[-1]] + ids[1:-1]
    return rounds


def make_rosters(rng: np.random.Generator, teams=TEAMS, size: int = 10) -> dict[str, list[dict]]:
    used, rosters = set(), {}
    for tid, _, _ in teams:
        roster = []
        while len(roster) < size:
            name = f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]}"
            if name in used:
                continue
            used.add(name)
            roster.append({"name": name, "weight": float(rng.uniform(0.5, 3.0))})
        rosters[tid] = roster
    return rosters


def generate(out_dir=MOCK_DIR, as_of: str = AS_OF, seed: int = SEED) -> None:
    use_league(LIIGA)
    rng = np.random.default_rng(seed)
    as_of_d = date.fromisoformat(as_of)
    ids = [t[0] for t in TEAMS]
    attack = {t: float(rng.normal(1.0, 0.12)) for t in ids}
    defence = {t: float(rng.normal(1.0, 0.12)) for t in ids}
    rosters = make_rosters(rng)

    base = round_robin(ids)
    schedule = []
    for cycle in range(4):  # 4 x 15 rounds = 60 games per team
        order = rng.permutation(len(base))
        for r in order:
            pairs = base[r] if cycle % 2 == 0 else [(b, a) for a, b in base[r]]
            schedule.append(pairs)

    games, events = [], {}
    for rnd, pairs in enumerate(schedule):
        gdate = START + timedelta(days=rnd * DAYS_PER_ROUND)
        for k, (h, a) in enumerate(pairs):
            g = {"id": f"G{rnd + 1:02d}{k + 1}", "round": rnd + 1, "date": gdate.isoformat(),
                 "time": "18:30", "home": h, "away": a, "status": "scheduled",
                 "home_goals": None, "away_goals": None, "decided": None}
            if gdate < as_of_d:
                lam_h = GOALS_PER_TEAM * attack[h] * defence[a] * LEAGUE.home_advantage
                lam_a = GOALS_PER_TEAM * attack[a] * defence[h]
                hg, ag, dec = simulate_result(lam_h, lam_a, rng)
                g.update(status="final", home_goals=hg, away_goals=ag, decided=dec)
                events[g["id"]] = generate_events(g, rosters[h], rosters[a], rng)
            games.append(g)

    out_dir.mkdir(parents=True, exist_ok=True)
    teams = [{"id": t, "name": n, "city": c, "roster": rosters[t]} for t, n, c in TEAMS]
    (out_dir / "teams.json").write_text(json.dumps(teams, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "games.json").write_text(json.dumps(games, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps({"as_of": as_of, "seed": seed, "note":
        "Fictional demo data. Team names are real clubs; players and results are invented."}),
        encoding="utf-8")


# Football demo: real Finnish club names, everything else invented. The 2026 line-up may differ.
FOOTBALL_TEAMS = [
    ("ACOULU", "AC Oulu", "Oulu"), ("HJK", "HJK", "Helsinki"), ("KUPS", "KuPS", "Kuopio"),
    ("SJK", "SJK", "Seinäjoki"), ("ILVES", "Ilves", "Tampere"), ("INTER", "FC Inter", "Turku"),
    ("LAHTI", "FC Lahti", "Lahti"), ("VPS", "VPS", "Vaasa"), ("GNISTAN", "Gnistan", "Helsinki"),
    ("JARO", "FF Jaro", "Pietarsaari"), ("MARIEHAMN", "IFK Mariehamn", "Maarianhamina"),
    ("HAKA", "FC Haka", "Valkeakoski"),
]
FOOTBALL_GOALS_PER_TEAM = 1.45
FOOTBALL_PLAYED_ROUNDS = 16          # of 22: the next round is on the demo's "today"


def generate_football(out_dir=MOCK_FOOTBALL_DIR, as_of: str = AS_OF, seed: int = SEED) -> None:
    """A 22-round double round robin, one round a week, 16 rounds played before `as_of`."""
    use_league(VEIKKAUSLIIGA)
    rng = np.random.default_rng(seed + 1)
    as_of_d = date.fromisoformat(as_of)
    ids = [t[0] for t in FOOTBALL_TEAMS]
    attack = {t: float(rng.normal(1.0, 0.15)) for t in ids}
    defence = {t: float(rng.normal(1.0, 0.15)) for t in ids}
    rosters = make_rosters(rng, FOOTBALL_TEAMS, 14)
    base = round_robin(ids)
    schedule = [base[r] for r in rng.permutation(len(base))]
    schedule += [[(b, a) for a, b in base[r]] for r in rng.permutation(len(base))]
    start = as_of_d - timedelta(weeks=FOOTBALL_PLAYED_ROUNDS)

    games, events = [], {}
    for rnd, pairs in enumerate(schedule):
        gdate = start + timedelta(weeks=rnd)
        for k, (h, a) in enumerate(pairs):
            g = {"id": f"F{rnd + 1:02d}{k + 1}", "round": rnd + 1, "date": gdate.isoformat(),
                 "time": ["15:00", "17:00", "19:00"][k % 3], "home": h, "away": a, "status": "scheduled",
                 "home_goals": None, "away_goals": None, "decided": None}
            if gdate < as_of_d:
                lam_h = FOOTBALL_GOALS_PER_TEAM * attack[h] * defence[a] * LEAGUE.home_advantage
                lam_a = FOOTBALL_GOALS_PER_TEAM * attack[a] * defence[h]
                hg, ag, dec = simulate_result(lam_h, lam_a, rng)
                g.update(status="final", home_goals=hg, away_goals=ag, decided=dec)
                events[g["id"]] = generate_events(g, rosters[h], rosters[a], rng)
            games.append(g)

    out_dir.mkdir(parents=True, exist_ok=True)
    teams = [{"id": t, "name": n, "city": c, "roster": rosters[t]} for t, n, c in FOOTBALL_TEAMS]
    (out_dir / "teams.json").write_text(json.dumps(teams, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "games.json").write_text(json.dumps(games, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps({"as_of": as_of, "seed": seed, "sport": "football", "note":
        "Fictional demo data. Team names are real Finnish football clubs; players and results are invented."}),
        encoding="utf-8")


if __name__ == "__main__":
    generate()
    generate_football()
    print(f"Mock seasons written to {MOCK_DIR} and {MOCK_FOOTBALL_DIR}")
