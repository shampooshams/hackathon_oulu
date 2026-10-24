"""Reliability tests: run with  python -m pytest -q"""
from companion.companion import PERSONAS, Companion
from companion.data.providers import MockProvider
from companion.facts import build_team_facts
from companion.live import apply_result, event_facts, postgame_facts, simulate_tonight
from companion.scenarios import simulate
from companion.stats import standings
from companion.verify import tamper, verify

SNAP = MockProvider().snapshot()
ODDS = simulate(SNAP, n=3000)
QUESTIONS = ["hi", "playoff chances?", "what's at stake tonight", "how is our form", "top scorer",
             "table", "last game", "should I bet", "any injuries?", "how are we at home?", "what's coming up?",
             "who leads the league?", "who is the top scorer in the league?", "thanks!", "what can you do?",
             "I'm so nervous about tonight", "how are you?"]


def test_standings_points_add_up():
    for r in standings(SNAP):
        assert r.pts == 3 * r.w + 2 * r.otw + r.otl
        assert r.gp == r.w + r.otw + r.otl + r.l


def test_probabilities_are_consistent():
    for t in SNAP.teams:
        total = ODDS.p_top6[t] + ODDS.p_playin[t] + ODDS.p_out[t]
        assert abs(total - 1) < 1e-9
        assert abs(sum(ODDS.rank_dist[t]) - 1) < 1e-9
        st = ODDS.stakes[t]
        assert st["top6_if_win"] >= st["top6_if_loss"] - 0.02  # winning shouldn't hurt


def test_every_offline_answer_verifies_for_every_team_and_persona():
    for team in SNAP.teams:
        fs = build_team_facts(SNAP, team, ODDS)
        for persona in PERSONAS:
            c = Companion(None, persona)
            for q in QUESTIONS:
                r = c.chat(fs, [], q)
                assert r.status == "verified", (team, persona, q, r.report.feedback(fs))
            assert c.brief(fs, "Sponsor").status == "verified"


def test_checker_catches_every_tampered_number():
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    c = Companion(None, "analyst")
    for q in QUESTIONS:
        text = c.chat(fs, [], q).text
        bad, what = tamper(text, fs)
        if what:
            assert not verify(bad, fs).ok, (q, what)


def test_checker_flags_uncited_and_unknown():
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    assert not verify("They have 99 points.", fs).ok           # number without citation
    assert not verify("They are great [F999].", fs).ok          # citation that doesn't exist
    assert verify("What a team! Top 6 is the goal.", fs).ok     # opinion, format words


def test_spelled_out_numbers_are_checked():
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    assert not verify(f"They have won seventeen games {fs.c('points')}.", fs).ok


class FakeLLM:
    """Hallucinates on the first call, corrects itself on the retry."""
    name = "Fake LLM"

    def __init__(self, fs):
        self.fs, self.calls = fs, 0

    def generate(self, system, messages, max_tokens=700):
        self.calls += 1
        if self.calls == 1:
            return f"We are 2nd with 40 points {self.fs.c('rank', 'points')}."
        return f"We are {self.fs.v('rank')} with {self.fs.v('points')} points {self.fs.c('rank', 'points')}."


def test_llm_hallucination_is_regenerated():
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    r = Companion(FakeLLM(fs), "buddy").chat(fs, [], "where are we?")
    assert r.status == "corrected" and r.report.ok


def test_game_night_pipeline():
    prof = {"predictions": {}, "alerts": {"top6_drop": True, "odds_below": 60}}
    for outcome in ("win", "loss"):
        game, events = simulate_tonight(SNAP, "KARPAT", 3, outcome)
        for ev in events:
            ef = event_facts(SNAP, game, ev)
            assert Companion().ping(ef, ev, "Kärpät").report.ok
        after = apply_result(SNAP, game, events)
        pf, alerts = postgame_facts(SNAP, after, "KARPAT", game, ODDS, simulate(after, n=2000), prof)
        assert Companion().postgame(pf, "Kärpät").status == "verified"
        for a in alerts:
            assert verify(a, pf).ok


def test_agent_routes_requests_to_tools():
    from companion.agent import keyword_route
    assert keyword_route("Make today's podcast")["tool"] == "podcast"
    assert keyword_route("I predict 3-2") == {"tool": "save_prediction", "home": 3, "away": 2}
    assert keyword_route("remind me if we fall below 30%") == {"tool": "set_alert", "threshold": 30}
    assert keyword_route("Should I bet on tonight's game?")["tool"] == "answer"   # no betting tool


def test_podcast_is_a_verified_two_host_dialogue():
    from companion.offline import HOSTS
    from companion.tts import script_lines
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    r = Companion(None, "buddy").podcast(fs, "Sponsor Oy")
    assert r.status == "verified", r.report.feedback(fs)
    lines = script_lines(r.text)
    assert {h for h, _ in lines} == set(HOSTS)
    assert not any("[F" in said for _, said in lines)        # citations are not read aloud
    assert any(said.startswith("Advertisement.") for _, said in lines)


def test_companion_declines_betting():
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    r = Companion(None, "stats").chat(fs, [], "Should I bet on tonight?")
    assert "don't do betting" in r.text and r.status == "verified"


import pytest  # noqa: E402


@pytest.mark.parametrize("sport", ["football", "floorball", "basketball", "bandy"])
def test_demo_sports_follow_their_rules_and_answers_verify(sport):
    from companion.config import FORMATS, LIIGA, use_league
    from companion.data.providers import get_provider
    fmt = FORMATS[sport]
    use_league(fmt)
    try:
        snap = get_provider(sport).snapshot()
        scen = simulate(snap, n=2000)
        for r in standings(snap):
            assert r.pts == (fmt.points_reg_win * r.w + fmt.points_ot_win * r.otw + fmt.points_ot_loss * r.otl
                             + fmt.points_draw * r.d)
            assert r.gp == r.w + r.otw + r.otl + r.d + r.l
            assert fmt.draws or r.d == 0
        for t in snap.teams:
            assert abs(scen.p_top6[t] + scen.p_playin[t] + scen.p_out[t] - 1) < 1e-9
        for g in snap.games:
            if g["status"] == "final":
                assert (g["home_goals"] == g["away_goals"]) == (fmt.draws and g["home_goals"] == g["away_goals"])
                evs = snap.events[g["id"]]
                assert (evs[-1]["home_score"], evs[-1]["away_score"]) == (g["home_goals"], g["away_goals"])
        team = next(iter(snap.teams))
        fs = build_team_facts(snap, team, scen)
        for q in QUESTIONS:
            r = Companion(None, "buddy").chat(fs, [], q)
            assert r.status == "verified", (sport, q, r.report.feedback(fs))
            assert "quarter-final" not in r.text
        pod = Companion(None, "buddy").podcast(fs, "Sponsor Oy")
        assert pod.status == "verified" and fmt.venue in pod.text
        game, events = simulate_tonight(snap, team, seed=3)
        assert events[-1]["type"] == "game_end"
        for ev in events:
            assert event_facts(snap, game, ev)
    finally:
        use_league(LIIGA)


def test_companion_compares_with_a_team_the_fan_mentions():
    from companion.facts import add_team_facts, find_teams
    fs = build_team_facts(SNAP, "KARPAT", ODDS)
    teams = find_teams(SNAP, "How do we compare to Tappara?", exclude="KARPAT")
    assert teams == ["TAPPARA"]
    add_team_facts(fs, SNAP, "KARPAT", "TAPPARA", ODDS)
    r = Companion(None, "buddy").chat(fs, [], "How do we compare to Tappara?")
    assert r.status == "verified" and "Tappara" in r.text and "Head-to-head" in r.text


def test_stakes_talk_about_a_race_tonight_can_move():
    import copy
    odds = copy.deepcopy(ODDS)
    team = SNAP.teams[0] if isinstance(SNAP.teams, list) else next(iter(SNAP.teams))
    c = Companion(None, "buddy")
    # Top places out of reach, playoff line still open: talk about the playoff line.
    odds.stakes[team].update(top6_if_win=0.0, top6_if_loss=0.0, top10_if_win=0.3, top10_if_loss=0.2)
    fs = build_team_facts(SNAP, team, odds)
    r = c.chat(fs, [], "what's at stake tonight")
    assert r.status == "verified" and "top 12 chance" in r.text and "swing" in r.text
    # Nothing tonight can change: say so instead of "<1% vs <1%, a swing of 0".
    odds.stakes[team].update(top10_if_win=0.003, top10_if_loss=0.002)
    fs = build_team_facts(SNAP, team, odds)
    r = c.chat(fs, [], "what's at stake tonight")
    assert r.status == "verified" and "won't move" in r.text and "swing" not in r.text

