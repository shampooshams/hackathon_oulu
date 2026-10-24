"""Liiga API adapter tests: run with  python -m pytest -q

The responses below are hand-made in the shapes of the Liiga stats API v1 docs
(ScheduleItemDTO, TeamDTO, GameDetailsDTO, StandingsResponseDTO). They are not real
results. Replace them with real files from api_samples/ once you have them.
"""
from companion.data.providers import LiigaApiProvider, team_key
from companion.stats import standings

KARPAT, TAPPARA, ASSAT, KESPOO = "461765763:kärpät", "362185137:tappara", "679171680:ässät", "1:k-espoo"


def sched(gid, home, away, hn, an, hg, ag, finished, ended=True, winner=None, start="2026-10-10T15:30:00Z"):
    return {"id": gid, "season": 2027, "homeTeamId": home, "awayTeamId": away, "homeTeamName": hn,
            "awayTeamName": an, "homeTeamGoals": hg, "awayTeamGoals": ag, "started": ended, "ended": ended,
            "homeTeamWinner": winner, "start": start, "finishedType": finished,
            "iceRink": {"city": {"kärpät": "Oulu", "tappara": "Tampere"}.get(home.split(":")[1], "")}}


SCHEDULE = [
    sched(1, KARPAT, TAPPARA, "Kärpät", "Tappara", 3, 1, "ENDED_DURING_REGULAR_GAME_TIME"),
    sched(2, ASSAT, KESPOO, "Ässät", "K-Espoo", 2, 3, "ENDED_DURING_EXTENDED_GAME_TIME"),
    sched(3, TAPPARA, ASSAT, "Tappara", "Ässät", 2, 2, "ENDED_DURING_WINNING_SHOT_COMPETITION", winner=True),
    sched(4, KESPOO, KARPAT, "K-Espoo", "Kärpät", None, None, "CANCELLED", ended=False),
    sched(5, KARPAT, ASSAT, "Kärpät", "Ässät", 0, 0, "ACTIVE_OR_NOT_STARTED", ended=False,
          start="2026-10-24T15:30:00Z"),
]
TEAMS = {"RUNKOSARJA": [{"id": "461765763", "shortName": "Kärpät"}, {"id": "362185137", "shortName": "Tappara"},
                        {"id": "679171680", "shortName": "Ässät"}, {"id": "1", "shortName": "K-Espoo"}]}
P = {10: ("ONNI", "AALTONEN"), 11: ("Aleksi", "Peltola"), 20: ("Eemil", "Keränen"), 30: ("Kasper", "Ahola")}


def player(pid):
    return {"id": pid, "firstName": P[pid][0], "lastName": P[pid][1]}


def goal(t, period, scorer, assists, hs, as_, types=()):
    return {"gameTime": t, "period": period, "eventId": t, "scorerPlayerId": scorer, "scorerPlayer": player(scorer),
            "assistantPlayerIds": assists, "assistantPlayers": [player(a) for a in assists],
            "homeTeamScore": hs, "awayTeamScore": as_, "goalTypes": list(types)}


DETAILS = {
    1: {"game": {"ended": True,
                 "homeTeam": {"goalEvents": [goal(376, 1, 10, [11], 1, 0, ["YV"]), goal(2500, 3, 10, [], 3, 1)],
                              "penaltyEvents": [{"gameTime": 266, "period": 1, "eventId": 33, "playerId": 11,
                                                 "penaltyMinutes": 2, "penaltyFaultName": "Koukkaaminen"}]},
                 "awayTeam": {"goalEvents": [goal(1500, 2, 20, [], 1, 1)]}},
        "homeTeamPlayers": [player(10), player(11)], "awayTeamPlayers": [player(20)]},
    2: {"game": {"ended": True, "homeTeam": {"goalEvents": [goal(100, 1, 30, [], 1, 0), goal(3000, 3, 30, [], 2, 2)]},
                 "awayTeam": {"goalEvents": [goal(1300, 2, 20, [], 1, 1), goal(1400, 2, 20, [], 1, 2),
                                             goal(3700, 4, 20, [], 2, 3)]}}},
    3: {"game": {"ended": True, "homeTeam": {"goalEvents": [goal(200, 1, 20, [], 1, 0), goal(2000, 2, 20, [], 2, 1)]},
                 "awayTeam": {"goalEvents": [goal(1000, 1, 30, [], 1, 1), goal(3100, 3, 30, [], 2, 2)]},
                 "winningShotCompetitionEvents": [{"shootingPlayerId": 20, "goalScored": True, "winningGoal": True}]},
        "homeTeamPlayers": [player(20)]},
}
STANDINGS = {"items": [
    {"teamId": KARPAT, "teamName": "Kärpät", "ranking": 1, "games": 1, "points": 3, "goals": 3, "goalsAgainst": 1},
    {"teamId": KESPOO, "teamName": "K-Espoo", "ranking": 2, "games": 1, "points": 2, "goals": 3, "goalsAgainst": 2},
    {"teamId": TAPPARA, "teamName": "Tappara", "ranking": 3, "games": 2, "points": 2, "goals": 4, "goalsAgainst": 5},
    {"teamId": ASSAT, "teamName": "Ässät", "ranking": 4, "games": 2, "points": 2, "goals": 4, "goalsAgainst": 6},
]}


def fake_get(path, **params):
    if path == "/api/v1/games/schedule":
        assert params == {"season": 2027, "serie": "RUNKOSARJA"}
        return SCHEDULE
    if path == "/api/v1/teams":
        return TEAMS
    if path.startswith("/api/v1/standings/"):
        return STANDINGS
    return DETAILS[int(path.rsplit("/", 1)[1])]


API = LiigaApiProvider(get=fake_get)
SNAP = API.snapshot()
GAMES = {g["id"]: g for g in SNAP.games}


def test_team_ids_match_the_mock_ids():
    assert team_key(KARPAT) == "KARPAT" and team_key(ASSAT) == "ASSAT" and team_key(KESPOO) == "KESPOO"
    assert set(SNAP.teams) == {"KARPAT", "TAPPARA", "ASSAT", "KESPOO"}
    assert SNAP.teams["KARPAT"] == {"id": "KARPAT", "name": "Kärpät", "city": "Oulu"}


def test_games_follow_the_contract():
    keys = {"id", "round", "date", "time", "home", "away", "status", "home_goals", "away_goals", "decided"}
    assert all(set(g) == keys for g in SNAP.games)
    assert "4" not in GAMES  # cancelled
    assert GAMES["1"] == {"id": "1", "round": None, "date": "2026-10-10", "time": "18:30", "home": "KARPAT",
                          "away": "TAPPARA", "status": "final", "home_goals": 3, "away_goals": 1, "decided": "REG"}
    assert GAMES["2"]["decided"] == "OT"
    assert (GAMES["3"]["home_goals"], GAMES["3"]["away_goals"], GAMES["3"]["decided"]) == (3, 2, "SO")
    assert GAMES["5"]["status"] == "scheduled" and GAMES["5"]["home_goals"] is None


def test_events_follow_the_contract():
    keys = {"game_id", "seq", "type", "period", "clock", "team", "player", "assists", "detail",
            "home_score", "away_score"}
    assert set(SNAP.events) == {"1", "2", "3"}
    for gid, evs in SNAP.events.items():
        assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
        assert all(set(e) == keys for e in evs)
        assert evs[-1]["type"] == "game_end"
        assert (evs[-1]["home_score"], evs[-1]["away_score"]) == (GAMES[gid]["home_goals"], GAMES[gid]["away_goals"])
    first = SNAP.events["1"]
    assert first[0] == {"game_id": "1", "seq": 1, "type": "penalty", "period": 1, "clock": "04:26",
                        "team": "KARPAT", "player": "Aleksi Peltola", "assists": [], "detail": "2 min, koukkaaminen",
                        "home_score": 0, "away_score": 0}
    assert first[1]["player"] == "Onni Aaltonen" and first[1]["detail"] == "power play"
    assert first[1]["assists"] == ["Aleksi Peltola"] and first[1]["clock"] == "06:16"
    ot = [e for e in SNAP.events["2"] if e["period"] == "OT"][0]
    assert (ot["clock"], ot["team"], ot["detail"]) == ("01:40", "KESPOO", "overtime winner")
    so = [e for e in SNAP.events["3"] if e["period"] == "SO"][0]
    assert (so["team"], so["player"], so["home_score"]) == ("TAPPARA", "Eemil Keränen", 3)


def test_computed_table_matches_official_table():
    ours = {r.team: r for r in standings(SNAP)}
    for o in API.official_standings():
        r = ours[o["team"]]
        assert (r.gp, r.pts, r.gf, r.ga) == (o["gp"], o["pts"], o["gf"], o["ga"]), o["name"]
