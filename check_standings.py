"""Check that the table we compute from real results matches the official Liiga table.

Usage:  python check_standings.py      (needs LIIGA_API_BASE and LIIGA_API_KEY in .env)
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from companion.data.providers import LiigaApiProvider  # noqa: E402
from companion.stats import standings  # noqa: E402

api = LiigaApiProvider()
ours = {r.team: r for r in standings(api.snapshot())}
official = api.official_standings()

print(f"{'Team':<12}{'Rank':>9}{'GP':>9}{'Pts':>10}{'GF':>9}{'GA':>9}   (ours/official)")
problems = 0
for o in official:
    r = ours.get(o["team"])
    if r is None:
        print(f"{o['name']:<12} missing from our data")
        problems += 1
        continue
    pairs = [(r.rank, o["rank"]), (r.gp, o["gp"]), (r.pts, o["pts"]), (r.gf, o["gf"]), (r.ga, o["ga"])]
    bad = any(a != b for a, b in pairs[1:])  # rank can differ on tie-breaks; the numbers must not
    problems += bad
    cells = "".join(f"{f'{a}/{b}':>9}" for a, b in pairs)
    print(f"{r.name:<12}{cells}{'   <-- differs' if bad else ''}")

print("\nAll teams match the official table." if not problems else f"\n{problems} team(s) differ.")
sys.exit(1 if problems else 0)
