"""The chat agent: decides which tool a fan's message needs.

With an AI model, the model picks the tool and its arguments (JSON). Without one,
or if its answer can't be parsed, simple keyword rules pick it. Tools only read
league data or change the fan's own settings. There is deliberately no betting tool.
"""
from __future__ import annotations

import json
import re

TOOLS = {
    "answer": "Answer a question about the team, table, form, players, stakes or the playoff race.",
    "podcast": "Make today's audio podcast episode (two hosts) about the team.",
    "set_alert": "Set an alert: notify if the team drops out of the top places, or if the top-places chance "
                 "falls below a threshold. Args: threshold = percent (number) or null.",
    "save_prediction": "Save the fan's score prediction for the next game. Args: home, away = goals (numbers) "
                       "for the home and away team.",
}

ROUTER = """You route a sports fan's message to ONE tool of a fan companion app.
Tools:
{tools}
The fan supports {team}; their next game is {fixture}.
Reply with JSON only, no prose, e.g. {{"tool": "save_prediction", "home": 3, "away": 2}}.
Use "answer" for questions, chit-chat and anything the other tools don't cover (including betting, which the
app doesn't do)."""


def _num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def keyword_route(message: str, team: str = "", opponent: str = "") -> dict:
    m = message.lower()
    if re.search(r"podcast|episode|audio show|radio show", m):
        return {"tool": "podcast"}
    score = re.search(r"\b(\d{1,2})\s*[-–:]\s*(\d{1,2})\b", m)
    if score and re.search(r"predict|prediction|my (tip|guess|call)|i think it.?ll", m):
        return {"tool": "save_prediction", "home": int(score.group(1)), "away": int(score.group(2))}
    if re.search(r"\b(remind|alert|notify|ping me|tell me (if|when)|let me know)\b", m):
        thr = re.search(r"(\d{1,3})\s*%", m)
        return {"tool": "set_alert", "threshold": int(thr.group(1)) if thr else None}
    return {"tool": "answer"}


def route(message: str, backend=None, team: str = "", opponent: str = "", fixture: str = "unknown") -> dict:
    """Return {"tool": ..., **args}. Falls back to keyword rules on any problem."""
    fallback = keyword_route(message, team, opponent)
    if backend is None:
        return fallback
    system = ROUTER.format(tools="\n".join(f"- {k}: {v}" for k, v in TOOLS.items()), team=team, fixture=fixture)
    try:
        raw = backend.generate(system, [{"role": "user", "content": message}], max_tokens=120)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except Exception:
        return fallback
    tool = data.get("tool")
    if tool not in TOOLS:
        return fallback
    out = {"tool": tool}
    if tool == "set_alert":
        out["threshold"] = _num(data.get("threshold"))
    elif tool == "save_prediction":
        h, a = _num(data.get("home")), _num(data.get("away"))
        if h is None or a is None:
            return fallback if fallback["tool"] == "save_prediction" else {"tool": "answer"}
        out["home"], out["away"] = int(h), int(a)
    return out


def follow_ups(last_question: str | None, opponent: str = "", top_label: str = "Playoff chances") -> dict[str, str]:
    """Quick-reply chips (label -> message) that fit where the conversation is."""
    from companion.offline import _intent
    pool = {
        "playoff": (top_label, "What are our playoff chances?"),
        "next": ("Tonight's stakes", "What's at stake tonight?"),
        "form": ("Our form", "How's our form?"),
        "home_away": ("Home vs away", "How are we doing at home and away?"),
        "schedule": ("What's coming up", "What's coming up?"),
        "scorer": ("Top scorer", "Who's our top scorer?"),
        "leaders": ("Who's top?", "Who leads the league?"),
        "compare": (f"vs {opponent}", f"How do we compare to {opponent}?") if opponent else None,
        "podcast": ("Today's podcast", "Make today's podcast"),
    }
    order = {
        None: ["playoff", "next", "podcast", "form"],
        "playoff": ["next", "compare", "form", "podcast"],
        "next": ["compare", "form", "home_away", "podcast"],
        "compare": ["next", "playoff", "home_away", "podcast"],
        "form": ["home_away", "schedule", "scorer", "playoff"],
        "home_away": ["schedule", "next", "form", "podcast"],
        "schedule": ["next", "playoff", "home_away", "podcast"],
        "scorer": ["leaders", "form", "next", "podcast"],
        "leaders": ["playoff", "compare", "scorer", "podcast"],
    }
    intent = _intent(last_question) if last_question else None
    if last_question and keyword_route(last_question)["tool"] == "podcast":
        intent = "podcast"
    keys = order.get(intent, ["playoff", "next", "form", "podcast"])
    if intent not in order:
        keys = [k for k in ["playoff", "next", "form", "home_away", "podcast"] if k != intent][:4]
    return dict(pool[k] for k in keys if pool.get(k))
