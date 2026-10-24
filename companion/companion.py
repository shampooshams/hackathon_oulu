"""The companion: writes chat answers, briefs, live pings and recaps, and runs
every output through the fact checker before it reaches the fan."""
from __future__ import annotations

from dataclasses import dataclass, field

from companion import offline
from companion.facts import FactStore
from companion.verify import Report, redact, tamper, verify

PERSONAS = {
    "buddy": ("Superfan buddy", "A warm, cheeky friend in the stands. Says 'we' about the team, shows emotion, "
                                "keeps it light, but never exaggerates the numbers."),
    "analyst": ("Calm analyst", "A clear, calm sports analyst. Explains what the numbers mean and why, "
                                "no hype, no filler."),
    "bettor": ("Bettor's notebook", "A neutral, data-first assistant for fans who follow betting. Focuses on form, "
                                    "probabilities and stakes. Never recommends a bet, never quotes bookmaker odds, "
                                    "and reminds the user to play responsibly when betting comes up."),
}
LENGTHS = {"short": "2–3 sentences", "normal": "4–6 sentences", "long": "two short paragraphs"}

RULES = """RULES (the app automatically checks these; answers that break them are blocked):
1. Every number you write (scores, points, positions like 6th, percentages, dates, times, counts) must be copied
   exactly from the FACTS, and the sentence must end with the ID(s) of the fact(s) it uses, e.g.
   "They are 6th with 25 points [F3][F4]."
2. Write numbers as digits. Never round, recompute, add or subtract numbers yourself; if a figure isn't in the
   FACTS, don't state it.
3. If the FACTS don't cover the question (injuries, line-ups, transfers, news, other leagues), say plainly that
   you don't have that data. Never guess.
4. Opinion, emotion and jokes are welcome, but only in sentences without numbers or factual claims about people.
5. Never recommend a bet. Model probabilities are not betting odds.
6. The 'fictional mock player' names are demo data: use them as given, invent nothing about them."""


@dataclass
class Reply:
    text: str
    facts: FactStore
    report: Report
    status: str                        # verified | corrected | redacted
    engine: str
    log: list[str] = field(default_factory=list)
    kind: str = "chat"


class Companion:
    def __init__(self, backend=None, persona: str = "buddy", length: str = "normal",
                 language: str = "English", user_name: str = ""):
        self.backend = backend
        self.persona = persona if persona in PERSONAS else "buddy"
        self.length = length
        self.language = language
        self.user_name = user_name

    @property
    def engine(self) -> str:
        return self.backend.name if self.backend else "Offline templates"

    def _system(self, team: str, fs: FactStore, task: str) -> str:
        name, desc = PERSONAS[self.persona]
        user = f"The user's name is {self.user_name}. " if self.user_name else ""
        return (f"You are '{name}', an AI sports companion from Kaleva Media for a fan of {team} "
                f"in Finland's Liiga. {desc}\n{user}Answer in {self.language}. Length: {LENGTHS.get(self.length)}.\n"
                f"TASK: {task}\n\n{RULES}\n\nFACTS:\n{fs.prompt_block()}")

    def _run(self, fs: FactStore, team: str, task: str, messages: list[dict], fallback, kind: str,
             simulate_error: bool = False, max_tokens: int = 700) -> Reply:
        log: list[str] = []
        engine = self.engine
        system = self._system(team, fs, task)

        def draft(msgs):
            nonlocal engine
            if self.backend:
                try:
                    return self.backend.generate(system, msgs, max_tokens=max_tokens)
                except Exception as e:  # network / quota: keep the demo alive
                    log.append(f"AI model unavailable ({type(e).__name__}), used offline templates.")
                    engine = "Offline templates (fallback)"
            return fallback()

        text = draft(messages)
        if simulate_error:
            text, what = tamper(text, fs)
            if what:
                log.append(f"Demo: injected a hallucination ({what}).")
        rep = verify(text, fs)
        status = "verified"
        if not rep.ok:
            log.append("Attempt 1 blocked by fact check:\n" + rep.feedback(fs))
            if self.backend and engine == self.engine:
                retry = messages + [{"role": "assistant", "content": text},
                                    {"role": "user", "content": "Your answer failed the automatic fact check:\n"
                                     + rep.feedback(fs) + "\nRewrite the full answer, using only numbers that "
                                     "appear in the cited facts. Do not mention the fact check."}]
                text = draft(retry)
            else:
                text = fallback()
            rep = verify(text, fs)
            status = "corrected"
            log.append("Attempt 2 " + ("passed." if rep.ok else "still failed, unverified sentences removed."))
            if not rep.ok:
                text = redact(text, rep)
                rep = verify(text, fs)
                status = "redacted"
        return Reply(text, fs, rep, status, engine, log, kind)

    # ---- public API -------------------------------------------------------
    def chat(self, fs: FactStore, history: list[dict], message: str, simulate_error=False) -> Reply:
        team = fs.v("team")
        msgs = [m for m in history[-8:] if m["role"] in ("user", "assistant")]
        msgs = msgs + [{"role": "user", "content": message}]
        return self._run(fs, team, "Chat with the fan and answer their latest message.", msgs,
                         lambda: offline.chat(message, fs, self.persona, self.user_name), "chat", simulate_error)

    def brief(self, fs: FactStore, sponsor: str = "", simulate_error=False) -> Reply:
        team = fs.v("team")
        ad = (f" Start right after the greeting with one clearly labelled ad line: '[Ad] Today's brief is "
              f"presented by {sponsor}.'" if sponsor else "")
        task = ("Write a spoken 45–60 second morning audio brief for game day: last result, table position, "
                "tonight's opponent and why the game matters for the playoff race, one player to watch. "
                "Short spoken sentences, one per line, no lists or markdown." + ad)
        return self._run(fs, team, task, [{"role": "user", "content": "Give me today's brief."}],
                         lambda: offline.brief(fs, self.persona, self.user_name, sponsor), "brief", simulate_error)

    def ping(self, fs: FactStore, ev: dict, fav_team: str, use_ai: bool = False) -> Reply:
        if not use_ai:
            text = offline.ping(ev, fs, fav_team)
            return Reply(text, fs, verify(text, fs), "verified", "Templates (live)", [], "ping")
        task = (f"Write ONE short live notification (max 2 sentences) about this game event for a {fav_team} fan. "
                f"Event type: {ev['type']}.")
        return self._run(fs, fav_team, task, [{"role": "user", "content": "New event."}],
                         lambda: offline.ping(ev, fs, fav_team), "ping", max_tokens=150)

    def postgame(self, fs: FactStore, team: str, simulate_error=False) -> Reply:
        task = ("Write the post-game recap for the fan: the result, the star of the night, how the table and the "
                "playoff chances changed, and how their prediction did if there is one.")
        return self._run(fs, team, task, [{"role": "user", "content": "The game just ended. Recap please."}],
                         lambda: offline.postgame(fs, self.persona), "postgame", simulate_error)
