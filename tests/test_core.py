"""Reliability tests: run with  python -m pytest -q"""
from companion.companion import Companion
from companion.data.providers import MockProvider
from companion.facts import build_team_facts
from companion.live import apply_result, event_facts, postgame_facts, simulate_tonight
from companion.scenarios import simulate
from companion.stats import standings
from companion.verify import tamper, verify

SNAP = MockProvider().snapshot()
ODDS = simulate(SNAP, n=3000)
QUESTIONS = ["hi", "playoff chances?", "what's at stake tonight", "how is our form", "top scorer",
             "table", "last game", "should I bet", "any injuries?"]


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
        for persona in ("buddy", "analyst", "bettor"):
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
