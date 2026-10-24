"""Data providers. Everything downstream only sees the normalised shapes
described in DATA_CONTRACT.md, so switching mock -> real API is one class."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from companion.config import AS_OF, DATA_DIR, MOCK_DIR

CACHE_DIR = DATA_DIR / "cache"
DEFAULT_BASE = "https://prod.liiga-backend.liiga.fi/stats"


@dataclass
class Snapshot:
    """Everything the companion knows about the league at one moment."""
    source: str
    is_mock: bool
    as_of: str
    teams: dict[str, dict]                  # id -> {id, name, city, roster?}
    games: list[dict]                       # see DATA_CONTRACT.md
    events: dict[str, list[dict]] = field(default_factory=dict)  # game_id -> events

    def name(self, team_id: str) -> str:
        return self.teams[team_id]["name"]

    def roster(self, team_id: str) -> list[dict]:
        roster = self.teams[team_id].get("roster")
        if roster:
            return roster
        # Fall back to players seen in event feeds
        seen: dict[str, int] = {}
        for evs in self.events.values():
            for e in evs:
                if e.get("team") == team_id and e.get("player"):
                    seen[e["player"]] = seen.get(e["player"], 0) + 1
        if not seen:
            return [{"name": f"{self.name(team_id)} skater", "weight": 1.0}]
        return [{"name": n, "weight": float(c)} for n, c in seen.items()]


class MockProvider:
    source_name = "Mock Liiga data"
    is_mock = True

    def __init__(self, path=MOCK_DIR):
        self.path = path
        if not (path / "games.json").exists():
            from companion.data.generate_mock import generate
            generate(path)

    def _load(self, name):
        return json.loads((self.path / name).read_text(encoding="utf-8"))

    def snapshot(self) -> Snapshot:
        meta = self._load("meta.json")
        teams = {t["id"]: t for t in self._load("teams.json")}
        return Snapshot(self.source_name, True, meta.get("as_of", AS_OF), teams,
                        self._load("games.json"), self._load("events.json"))


class LiigaApiProvider:
    """Adapter for the Liiga stats API (v1) provided by Kaleva.

    Endpoints (see the Swagger docs at <base>/swagger-ui/index.html?urls.primaryName=v1):
      teams     GET /api/v1/teams?serie=RUNKOSARJA&season=2027
      fixtures  GET /api/v1/games/schedule?serie=RUNKOSARJA&season=2027
      events    GET /api/v1/games/{season}/{gameId}   (goal and penalty events per team)
      table     GET /api/v1/standings/RUNKOSARJA?season=2027   (only used to check our table)
    The key goes in the x-api-key header. Finished games never change, so their
    details are cached in data/cache/ to keep reloads fast.
    """
    source_name = "Liiga API"
    is_mock = False

    SERIE = "RUNKOSARJA"
    TEAMS_PATH = "/api/v1/teams"
    GAMES_PATH = "/api/v1/games/schedule"
    EVENTS_PATH = "/api/v1/games/{season}/{game_id}"
    STANDINGS_PATH = "/api/v1/standings/{serie}"

    def __init__(self, get=None):
        self.base = (os.getenv("LIIGA_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.key = os.getenv("LIIGA_API_KEY", "")
        self.season = int(os.getenv("LIIGA_SEASON") or 2027)
        self._get_override = get          # tests pass a fake here; the key is optional (sent only if set)

    def _get(self, path: str, **params):
        if self._get_override:
            return self._get_override(path, **params)
        import requests
        headers = {"x-api-key": self.key} if self.key else {}
        r = requests.get(self.base + path, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def _game_details(self, game_id: str) -> dict:
        cache = CACHE_DIR / f"game_{self.season}_{game_id}.json"
        if cache.exists() and not self._get_override:
            return json.loads(cache.read_text(encoding="utf-8"))
        raw = self._get(self.EVENTS_PATH.format(season=self.season, game_id=game_id))
        if not self._get_override and (raw.get("game") or {}).get("ended"):
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return raw

    def snapshot(self) -> Snapshot:
        schedule = self._get(self.GAMES_PATH, season=self.season, serie=self.SERIE)
        games = [g for g in map(normalise_game, schedule) if g is not None]
        teams = teams_from(self._get(self.TEAMS_PATH, season=self.season, serie=self.SERIE), schedule)

        finals = [g for g in games if g["status"] == "final"]
        workers = 1 if self._get_override else 8
        with ThreadPoolExecutor(max_workers=workers) as pool:
            details = list(pool.map(self._game_details, [g["id"] for g in finals]))
        events = {g["id"]: game_events(d, g) for g, d in zip(finals, details)}
        return Snapshot(self.source_name, False, date.today().isoformat(), teams, games, events)

    def official_standings(self) -> list[dict]:
        """The league's own table, used to check that our computed table matches."""
        raw = self._get(self.STANDINGS_PATH.format(serie=self.SERIE), season=self.season)
        return [{"team": team_key(i["teamId"], i.get("teamName")), "name": i.get("teamName"),
                 "rank": i.get("ranking"), "gp": i.get("games"), "pts": i.get("points"),
                 "gf": i.get("goals"), "ga": i.get("goalsAgainst")}
                for i in raw.get("items", [])]


# ---------- mapping the API's shapes to DATA_CONTRACT.md -----------------------

FINISHED = {"ENDED_DURING_REGULAR_GAME_TIME": "REG", "ENDED_DURING_EXTENDED_GAME_TIME": "OT",
            "ENDED_DURING_WINNING_SHOT_COMPETITION": "SO"}
GOAL_TYPES = {"YV": "power play", "YV2": "5-on-3 power play", "AV": "shorthanded",
              "TM": "empty net", "RL": "penalty shot"}
PERIOD_SECONDS = 20 * 60


def team_key(raw_id, name: str | None = None) -> str:
    """'461765763:kärpät' or a name like 'Kärpät' -> 'KARPAT' (the same ids the mock data uses)."""
    s = str(raw_id or "")
    slug = s.split(":", 1)[1] if ":" in s else (name or s)
    ascii_ = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", ascii_.upper())


def _local(start: str) -> datetime | None:
    """API times are UTC ('2025-09-15T17:30:00Z'); show them in Finnish time."""
    if not start:
        return None
    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("Europe/Helsinki"))
    except Exception:  # no tz database installed
        return dt


def _name(player: dict | None) -> str | None:
    if not player:
        return None
    full = f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()
    return full.title() if full.isupper() else (full or None)


def teams_from(raw_teams, schedule: list[dict]) -> dict[str, dict]:
    """Teams come from /teams (a map of lists); the schedule fills in ids, names and home cities."""
    teams: dict[str, dict] = {}
    lists = raw_teams.values() if isinstance(raw_teams, dict) else [raw_teams or []]
    for items in lists:
        for t in items or []:
            nt = normalise_team(t)
            teams[nt["id"]] = nt
    cities: dict[str, dict[str, int]] = {}
    for g in schedule:
        for side in ("home", "away"):
            tid = team_key(g.get(f"{side}TeamId"), g.get(f"{side}TeamName"))
            if tid and tid not in teams:
                teams[tid] = {"id": tid, "name": g.get(f"{side}TeamName") or tid, "city": ""}
        city = (g.get("iceRink") or {}).get("city")
        if city:
            home = team_key(g.get("homeTeamId"), g.get("homeTeamName"))
            cities.setdefault(home, {})[city] = cities.setdefault(home, {}).get(city, 0) + 1
    for tid, seen in cities.items():
        if tid in teams and not teams[tid].get("city"):
            teams[tid]["city"] = max(seen, key=seen.get)
    # Only keep teams that actually play in this serie
    playing = {team_key(g.get(f"{s}TeamId"), g.get(f"{s}TeamName")) for g in schedule for s in ("home", "away")}
    return {k: v for k, v in teams.items() if k in playing} if playing else teams


def normalise_team(raw: dict) -> dict:
    """TeamDTO: {id, nameAbbreviation, shortName, logos}."""
    name = raw.get("shortName") or raw.get("nameAbbreviation") or str(raw.get("id"))
    return {"id": team_key(raw.get("id"), name), "name": name, "city": raw.get("city", "")}


def normalise_game(raw: dict) -> dict | None:
    """ScheduleItemDTO -> Game. Cancelled games are dropped; games in progress count as scheduled."""
    finished = raw.get("finishedType") or "ACTIVE_OR_NOT_STARTED"
    if finished == "CANCELLED":
        return None
    decided = FINISHED.get(finished)
    final = bool(raw.get("ended")) and decided is not None
    start = _local(raw.get("start") or "")
    hg, ag = raw.get("homeTeamGoals"), raw.get("awayTeamGoals")
    if final and hg == ag:  # shootout winner's +1 goal, if the API doesn't include it
        if raw.get("homeTeamWinner"):
            hg += 1
        else:
            ag += 1
    return {"id": str(raw.get("id")), "round": raw.get("gameWeek"),
            "date": start.date().isoformat() if start else "",
            "time": start.strftime("%H:%M") if start else "",
            "home": team_key(raw.get("homeTeamId"), raw.get("homeTeamName")),
            "away": team_key(raw.get("awayTeamId"), raw.get("awayTeamName")),
            "status": "final" if final else "scheduled",
            "home_goals": hg if final else None, "away_goals": ag if final else None,
            "decided": decided if final else None}


def _clock(period: int, game_time: int) -> tuple[int | str, str]:
    """API gameTime counts seconds from the start of the game; the contract wants time in the period."""
    period = period or (min(game_time // PERIOD_SECONDS, 3) + 1)
    secs = max(0, game_time - (period - 1) * PERIOD_SECONDS)
    return ("OT" if period >= 4 else period), f"{secs // 60:02d}:{secs % 60:02d}"


def normalise_event(raw: dict, game: dict, kind: str = "goal", team: str | None = None,
                    players: dict | None = None) -> dict:
    """GoalEventDTO or PenaltyEventDTO -> Event. seq and running scores are set by game_events()."""
    players = players or {}
    period, clock = _clock(raw.get("period"), raw.get("gameTime") or 0)
    if kind == "goal":
        detail = ", ".join(GOAL_TYPES.get(t, t) for t in sorted(raw.get("goalTypes") or []) if t != "VL")
        if period == "OT":
            detail = ", ".join(x for x in ("overtime winner", detail) if x)
        return {"game_id": game["id"], "seq": None, "type": "goal", "period": period, "clock": clock,
                "team": team, "player": _name(raw.get("scorerPlayer")) or players.get(raw.get("scorerPlayerId")),
                "assists": [n for n in (_name(p) for p in raw.get("assistantPlayers") or []) if n]
                or [players[i] for i in raw.get("assistantPlayerIds") or [] if i in players],
                "detail": detail, "home_score": raw.get("homeTeamScore"), "away_score": raw.get("awayTeamScore")}
    fault = (raw.get("penaltyFaultName") or raw.get("penaltyFaultType") or "").lower()
    return {"game_id": game["id"], "seq": None, "type": "penalty", "period": period, "clock": clock,
            "team": team, "player": players.get(raw.get("playerId")), "assists": [],
            "detail": f"{raw.get('penaltyMinutes', 2)} min" + (f", {fault}" if fault else ""),
            "home_score": None, "away_score": None}


def game_events(details: dict, game: dict) -> list[dict]:
    """GameDetailsDTO -> the ordered event feed for one finished game."""
    g = details.get("game") or {}
    players = {p.get("id"): _name(p) for p in
               (details.get("homeTeamPlayers") or []) + (details.get("awayTeamPlayers") or [])}
    raw = []
    for side, tid in (("homeTeam", game["home"]), ("awayTeam", game["away"])):
        t = g.get(side) or {}
        raw += [(e.get("gameTime") or 0, 1, e.get("eventId") or 0, normalise_event(e, game, "goal", tid, players))
                for e in t.get("goalEvents") or []]
        raw += [(e.get("gameTime") or 0, 0, e.get("eventId") or 0, normalise_event(e, game, "penalty", tid, players))
                for e in t.get("penaltyEvents") or []]
    for p in (1, 2, 3):
        end = {"game_id": game["id"], "seq": None, "type": "period_end", "period": p, "clock": "20:00",
               "team": None, "player": None, "assists": [], "detail": f"End of period {p}",
               "home_score": None, "away_score": None}
        raw.append((p * PERIOD_SECONDS, 2, 0, end))
    raw.sort(key=lambda x: (x[0], x[1], x[2]))
    events = [x[3] for x in raw]

    if game["decided"] == "SO":
        shots = g.get("winningShotCompetitionEvents") or []
        win = next((s for s in shots if s.get("winningGoal")), None)
        winner = game["home"] if game["home_goals"] > game["away_goals"] else game["away"]
        events.append({"game_id": game["id"], "seq": None, "type": "goal", "period": "SO", "clock": "",
                       "team": winner, "player": players.get(win.get("shootingPlayerId")) if win else None,
                       "assists": [], "detail": "shootout winner",
                       "home_score": game["home_goals"], "away_score": game["away_goals"]})
    events.append({"game_id": game["id"], "seq": None, "type": "game_end", "period": None, "clock": "",
                   "team": None, "player": None, "assists": [],
                   "detail": "Final" if game["decided"] == "REG" else f"Final ({game['decided']})",
                   "home_score": game["home_goals"], "away_score": game["away_goals"]})

    hs = as_ = 0
    for i, e in enumerate(events, 1):
        e["seq"] = i
        if e["type"] == "goal" and e["period"] != "SO":
            if e["home_score"] is None or e["away_score"] is None:
                e["home_score"], e["away_score"] = hs + (e["team"] == game["home"]), as_ + (e["team"] == game["away"])
            hs, as_ = e["home_score"], e["away_score"]
        elif e["home_score"] is None:
            e["home_score"], e["away_score"] = hs, as_
    return events


def get_provider(kind: str = "mock"):
    return LiigaApiProvider() if kind == "liiga" else MockProvider()
