"""The companion's memory of the user: a small JSON profile per user."""
from __future__ import annotations

import json
import re

from companion.config import USERS_DIR

DEFAULT = {
    "name": "",
    "team": "KARPAT",
    "persona": "buddy",
    "length": "normal",
    "language": "English",
    "fan_since": "",
    "fav_player": "",
    "predictions": {},          # game_id -> {"home": int, "away": int}
    "alerts": {"top6_drop": True, "odds_below": 50},
}


def _path(user_id: str):
    slug = re.sub(r"[^a-z0-9_-]", "", user_id.lower()) or "demo"
    return USERS_DIR / f"{slug}.json"


def load_profile(user_id: str = "demo") -> dict:
    p = _path(user_id)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    prof = {**DEFAULT, **data}
    prof["alerts"] = {**DEFAULT["alerts"], **(data.get("alerts") or {})}
    return prof


def save_profile(profile: dict, user_id: str = "demo") -> None:
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    _path(user_id).write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
