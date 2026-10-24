"""Offline template writer — used when no LLM key is set, or if the LLM call fails.

Same contract as the LLM: every number is copied from a fact and cited, so the
same checker verifies it. Less fluent than an LLM, but never breaks a demo.
"""
from __future__ import annotations

import re

from companion.config import LEAGUE
from companion.facts import FactStore
from companion.stats import ordinal



def _loss() -> str:
    """What 'not winning' means: in football a draw also costs points against a win."""
    return "a draw or loss" if LEAGUE.draws else "a loss"


def _who(fs: FactStore, persona: str, cap: bool = True) -> str:
    if persona == "buddy":
        return "We" if cap else "we"
    return fs.v("team")


def _s(fs: FactStore, text: str, *keys: str) -> str:
    """Sentence with citations for the given keys (skips silently if a key is missing)."""
    return f"{text} {fs.c(*keys)}".strip()


def _intent(msg: str) -> str:
    m = msg.lower()
    rules = [
        ("greet", r"^\s*(hi|hey|hello|moi|terve|hei)\b"),
        ("bet", r"\bbet|odds|wager|tip|gamble"),
        ("playoff", r"playoff|chance|top.?6|top.?six|make it|qualif|season end|finish"),
        ("next", r"tonight|next (game|match)|stake|who do we play|who are we playing|preview|today"),
        ("scorer", r"scor|goal|best player|points leader|who.*(leading|best)"),
        ("form", r"form|lately|recent|streak|how are we|how.*doing|momentum"),
        ("last", r"last (game|night|match)|yesterday|result"),
        ("table", r"table|standing|rank|position|where are we|place"),
    ]
    for name, pat in rules:
        if re.search(pat, m):
            return name
    return "summary"


def _opener(persona: str) -> str:
    return {"buddy": "Okay, here's the deal.", "analyst": "Here's the picture.",
            "stats": "Numbers first."}.get(persona, "")


def chat(message: str, fs: FactStore, persona: str, user_name: str = "") -> str:
    W, w = _who(fs, persona), _who(fs, persona, cap=False)
    T = fs.v("team")
    intent = _intent(message)
    out: list[str] = []

    if intent == "greet":
        hi = f"Hei {user_name}!" if user_name else "Hei!"
        out.append(f"{hi} Your {T} companion here.")
        if fs.has("next_game"):
            out.append(_s(fs, f"Next up: {fs.v('next_game')}.", "next_game"))
        out.append("Ask me about the table, our form, tonight's stakes or the playoff race.")
    elif intent == "playoff":
        out.append(_opener(persona))
        out.append(_s(fs, f"{W} sit {fs.v('rank')} with {fs.v('points')} points after {fs.v('gp')} games.",
                      "rank", "points", "gp"))
        out.append(_s(fs, f"That's {fs.v('gap6')}.", "gap6"))
        if fs.has("p_top6"):
            reach = (f" and {LEAGUE.reach_goal} (top {LEAGUE.playin_last}) in {fs.v('p_top10')}"
                     if fs.has("p_top10") else "")
            out.append(_s(fs, f"Across the simulated rest of the season, {w} finish in the top {LEAGUE.direct_spots} "
                              f"({LEAGUE.direct_goal}) in {fs.v('p_top6')} of runs{reach}.", "p_top6", "p_top10"))
            out.append(_s(fs, f"The {ordinal(LEAGUE.direct_spots)}-placed team typically ends on about {fs.v('cutline')}, and {w} are "
                              f"projected at {fs.v('proj_points')}.", "cutline", "proj_points"))
        if fs.has("stake_win"):
            out.append(_s(fs, f"Tonight matters: a win lifts the top-{LEAGUE.direct_spots} chance to {fs.v('stake_win')}, "
                              f"{_loss()} drops it to {fs.v('stake_loss')}.", "stake_win", "stake_loss"))
        if persona == "buddy":
            out.append("Long way to go, but every point counts from here.")
    elif intent == "next":
        if not fs.has("next_game"):
            return "There's no upcoming game in the fixtures I have."
        out.append(_s(fs, f"Next game: {fs.v('next_game')}.", "next_game"))
        opp = fs.get("opp_rank").label.replace(" league position", "")
        out.append(_s(fs, f"{opp} are {fs.v('opp_rank')} with {fs.v('opp_points')} points, recent form "
                          f"{fs.v('opp_form5')}.", "opp_rank", "opp_points", "opp_form5"))
        out.append(_s(fs, f"Head-to-head: {fs.v('h2h')}.", "h2h"))
        if fs.has("stake_win"):
            out.append(_s(fs, f"What's at stake: win and the top-{LEAGUE.direct_spots} chance goes to {fs.v('stake_win')}, "
                              f"{'drop points' if LEAGUE.draws else 'lose'} and it's {fs.v('stake_loss')}, a swing of {fs.v('stake_swing')}.",
                          "stake_win", "stake_loss", "stake_swing"))
        if fs.has("prediction"):
            out.append(_s(fs, f"Your call on record: {fs.v('prediction')}.", "prediction"))
        if persona == "buddy":
            out.append("Big one. Bring your voice!")
    elif intent == "bet":
        out.append("I don't do betting: no tips, odds or bet slips. Happy to talk about the game itself, though.")
        if fs.has("next_game"):
            out.append(_s(fs, f"Next up: {fs.v('next_game')}.", "next_game"))
        out.append(_s(fs, f"Recent form: {fs.v('form5')}.", "form5"))
        if fs.has("opp_form5"):
            out.append(_s(fs, f"Opponent form: {fs.v('opp_form5')}.", "opp_form5"))
    elif intent == "scorer":
        if fs.has("top_scorer"):
            out.append(_s(fs, f"Top goalscorer: {fs.v('top_scorer')}.", "top_scorer"))
            out.append(_s(fs, f"Points leader: {fs.v('top_points')}.", "top_points"))
        else:
            out.append("I don't have scorer data yet.")
        if fs.has("fav_player"):
            out.append(f"I know {fs.v('fav_player')} is your favourite, I'll flag every goal of theirs on game night. {fs.c('fav_player')}")
    elif intent == "form":
        out.append(_s(fs, f"Last results, oldest to newest: {fs.v('form5')}, worth {fs.v('form5_pts')} points.",
                      "form5", "form5_pts"))
        out.append(_s(fs, f"Current streak: {fs.v('streak')}.", "streak"))
        out.append(_s(fs, f"Season record ({fs.get('record').label.split('(')[-1].rstrip(')')}) is {fs.v('record')} with a {LEAGUE.score_word} difference of {fs.v('gd')}.",
                      "record", "gd"))
    elif intent == "last":
        out.append(_s(fs, f"Last game: {fs.v('last_game')}.", "last_game"))
        out.append(_s(fs, f"That leaves {T} {fs.v('rank')} on {fs.v('points')} points.", "rank", "points"))
    elif intent == "table":
        out.append(_s(fs, f"{W} are {fs.v('rank')} with {fs.v('points')} points from {fs.v('gp')} games.",
                      "rank", "points", "gp"))
        out.append(_s(fs, f"{fs.v('gap6')[0].upper()}{fs.v('gap6')[1:]}.", "gap6"))
        out.append(_s(fs, f"League leader: {fs.v('leader')}.", "leader"))
    else:
        out.append(_s(fs, f"Quick update: {T} are {fs.v('rank')} on {fs.v('points')} points, form {fs.v('form5')}.",
                      "rank", "points", "form5"))
        if fs.has("next_game"):
            out.append(_s(fs, f"Next: {fs.v('next_game')}.", "next_game"))
        out.append("I only answer from league data, so I can't speak to injuries, transfers or news. "
                   "Try asking about the playoff race, tonight's game, form or top scorers.")
    return " ".join(x for x in out if x)


def brief(fs: FactStore, persona: str, user_name: str = "", sponsor: str = "") -> str:
    T = fs.v("team")
    name = f", {user_name}" if user_name else ""
    parts = [f"Huomenta{name}! This is your {T} brief."]
    if sponsor:
        parts.append(f"[Ad] Today's brief is presented by {sponsor}.")
    parts.append(_s(fs, f"Last time out: {fs.v('last_game')}.", "last_game"))
    parts.append(_s(fs, f"{T} are {fs.v('rank')} on {fs.v('points')} points, {fs.v('gap6')}.",
                    "rank", "points", "gap6"))
    if fs.has("next_game"):
        parts.append(_s(fs, f"Tonight: {fs.v('next_game')}.", "next_game"))
        parts.append(_s(fs, f"The opponent sits {fs.v('opp_rank')} with recent form {fs.v('opp_form5')}.",
                        "opp_rank", "opp_form5"))
    if fs.has("stake_win"):
        parts.append(_s(fs, f"Why it matters: a win takes the top-{LEAGUE.direct_spots} chance to {fs.v('stake_win')}, "
                            f"{_loss()} leaves it at {fs.v('stake_loss')}.", "stake_win", "stake_loss"))
    if fs.has("top_scorer"):
        parts.append(_s(fs, f"Player to watch: {fs.v('top_scorer')}.", "top_scorer"))
    parts.append("That's your brief. Enjoy the game!" if persona == "buddy" else "That's the brief for today.")
    return "\n".join(parts)


HOSTS = ("Aino", "Mikko")   # Aino: the fan in the stands, Mikko: the calm analyst


def podcast(fs: FactStore, sponsor: str = "", short: bool = False) -> str:
    """Two-host episode, one line per turn as 'Name: text'."""
    a, m = HOSTS
    T = fs.v("team")
    lines = [f"{a}: Hei and welcome to the {T} companion podcast! I'm {a}.",
             f"{m}: And I'm {m}. Everything we say today comes straight from the Liiga data."]
    if sponsor:
        lines.append(f"{a}: [Ad] This episode is presented by {sponsor}.")
    if fs.has("last_game"):
        lines.append(f"{a}: " + _s(fs, f"Let's start with the last game: {fs.v('last_game')}.", "last_game"))
    lines.append(f"{m}: " + _s(fs, f"That leaves {T} {fs.v('rank')} on {fs.v('points')} points, "
                                   f"{fs.v('gap6')}.", "rank", "points", "gap6"))
    if fs.has("form5") and not short:
        lines.append(f"{a}: " + _s(fs, f"Recent form reads {fs.v('form5')}, and the streak: {fs.v('streak')}.",
                                   "form5", "streak"))
    if fs.has("next_game"):
        lines.append(f"{a}: " + _s(fs, f"Next up: {fs.v('next_game')}.", "next_game"))
        lines.append(f"{m}: " + _s(fs, f"The opponent sits {fs.v('opp_rank')} with recent form {fs.v('opp_form5')}.",
                                   "opp_rank", "opp_form5"))
    if fs.has("stake_win"):
        lines.append(f"{a}: So how big is it?")
        lines.append(f"{m}: " + _s(fs, f"A win takes the top-{LEAGUE.direct_spots} chance to {fs.v('stake_win')}, "
                                       f"{_loss()} leaves it at {fs.v('stake_loss')}.", "stake_win", "stake_loss"))
    if fs.has("p_top10") and not short:
        lines.append(f"{m}: " + _s(fs, f"Over the whole season, the simulations put {T} in the top {LEAGUE.playin_last} in "
                                       f"{fs.v('p_top10')} of runs.", "p_top10"))
    if fs.has("top_scorer"):
        lines.append(f"{a}: " + _s(fs, f"Player to watch: {fs.v('top_scorer')}.", "top_scorer"))
    lines.append(f"{m}: That's the numbers. The rest is up to the players.")
    lines.append(f"{a}: See you at the {LEAGUE.venue}. Hyvä {T}!")
    return "\n".join(lines)


def ping(ev: dict, fs: FactStore, fav_team_name: str) -> str:
    t = ev["type"]
    if t == "goal":
        ours = fs.v("ev_team") == fav_team_name
        if ev.get("period") == "SO":
            head = "SHOOTOUT WINNER!" if ours else "Shootout lost."
            return _s(fs, f"{head} {fs.v('player')} decides it for {fs.v('ev_team')}, final {fs.v('score')}.",
                      "player", "ev_team", "score")
        head = "GOAL!" if ours else "Goal against."
        text = _s(fs, f"{head} {fs.v('player')} scores for {fs.v('ev_team')} ({fs.v('time')}), {fs.v('score')}.",
                  "player", "ev_team", "time", "score")
        if fs.has("assists"):
            text += " " + _s(fs, f"Assists: {fs.v('assists')}.", "assists")
        return text
    if t == "card":
        return _s(fs, f"{fs.v('detail')}: {fs.v('player')} ({fs.v('ev_team')}), {fs.v('time')}.",
                  "detail", "player", "ev_team", "time")
    if t == "penalty":
        return _s(fs, f"Penalty: {fs.v('player')} ({fs.v('ev_team')}), {fs.v('detail')}, at {fs.v('time')}.",
                  "player", "ev_team", "detail", "time")
    if t == "period_end":
        return _s(fs, f"{fs.v('detail')}, score {fs.v('score')}.", "detail", "score")
    if t == "game_end":
        return _s(fs, f"{fs.v('detail')}: {fs.v('score')}.", "detail", "score")
    return ""


def postgame(fs: FactStore, persona: str) -> str:
    T = fs.get("points_after").label.replace(" points now", "")
    won = fs.v("result").startswith("win")
    out = []
    if persona == "buddy":
        out.append("What a night!" if won else "Honours even tonight." if fs.v("result") == "draw"
                   else "Tough one tonight.")
    out.append(_s(fs, f"Final: {fs.v('final')}, a {fs.v('result')} worth {fs.v('points_earned')} "
                      f"point{'s' if fs.v('points_earned') != '1' else ''}.", "final", "result", "points_earned"))
    if fs.has("star"):
        out.append(_s(fs, f"Star of the night: {fs.v('star')}.", "star"))
    out.append(_s(fs, f"{T} move from {fs.v('rank_before')} to {fs.v('rank_after')} on {fs.v('points_after')} "
                      f"points, with tonight's other games still to finish.",
                  "rank_before", "rank_after", "points_after"))
    out.append(_s(fs, f"Top-{LEAGUE.direct_spots} chance: {fs.v('top6_before')} before the game, {fs.v('top6_after')} now "
                      f"({fs.v('top6_change')}).", "top6_before", "top6_after", "top6_change"))
    if fs.has("prediction"):
        out.append(_s(fs, f"Your prediction ({fs.v('prediction')}): {fs.v('prediction_verdict')}.",
                      "prediction", "prediction_verdict"))
    return " ".join(out)
