"""Save sample responses from the Liiga API so the data mapping can be checked.

Usage (from the project folder, with LIIGA_API_BASE and LIIGA_API_KEY in .env):
    python probe_api.py            # finds the right base URL, then saves the main endpoints
    python probe_api.py /api/v1/games/schedule?season=2027&serie=RUNKOSARJA   # any other path
Each response is saved as a JSON file in api_samples/.
"""
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
BASE = (os.getenv("LIIGA_API_BASE") or "https://prod.liiga-backend.liiga.fi/stats").rstrip("/")
KEY = os.getenv("LIIGA_API_KEY", "")
SEASON = os.getenv("LIIGA_SEASON", "2027")
HEADERS = {"x-api-key": KEY}  # from the docs: securitySchemes.ApiKeyAuth

out = Path("api_samples")
out.mkdir(exist_ok=True)


def find_base() -> str:
    """The docs list the server as '/api' and paths as '/api/v1/...', so try the likely combinations."""
    host = re.match(r"https?://[^/]+", BASE).group(0)
    for base in dict.fromkeys([BASE, BASE.removesuffix("/api"), host + "/stats", host]):
        try:
            r = requests.get(base + "/api/v1/test", headers=HEADERS, timeout=20)
            print(f"{base}/api/v1/test: HTTP {r.status_code} {r.text[:40]!r}")
            if r.ok:
                return base
        except requests.RequestException as e:
            print(f"{base}/api/v1/test: {e.__class__.__name__}")
    sys.exit("No base URL answered. Are you on the network/VPN where the Swagger page opens?")


def save(base: str, path: str) -> dict | list | None:
    r = requests.get(base + path, headers=HEADERS, timeout=30)
    name = re.sub(r"[^A-Za-z0-9]+", "_", path.replace("/api/v1/", "")).strip("_") or "root"
    try:
        data = r.json()
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except ValueError:
        data = None
        (out / f"{name}.txt").write_text(r.text[:200_000], encoding="utf-8")
    print(f"{path}: HTTP {r.status_code} -> api_samples/{name}")
    return data


base = find_base()
if base != BASE:
    print(f"\nPut this in .env:  LIIGA_API_BASE={base}\n")
paths = sys.argv[1:] or [f"/api/v1/teams?season={SEASON}&serie=RUNKOSARJA",
                         f"/api/v1/games/schedule?season={SEASON}&serie=RUNKOSARJA",
                         f"/api/v1/standings/RUNKOSARJA?season={SEASON}"]
for p in paths:
    data = save(base, p)
    if "games/schedule" in p and isinstance(data, list):  # also save one finished game's events
        done = [g for g in data if g.get("ended")]
        if done:
            save(base, f"/api/v1/games/{SEASON}/{done[-1]['id']}")
