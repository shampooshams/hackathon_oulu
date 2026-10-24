"""Offline template writer — used when no LLM key is set, or if the LLM call fails.

Same contract as the LLM: every number is copied from a fact and cited, so the
same checker verifies it. Less fluent than an LLM, but never breaks a demo.
"""
from __future__ import annotations

import re

from companion.facts import FactStore


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
            "bettor": "Notebook check."}.get(persona, "")


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
            out.append(_s(fs, f"Across the simulated rest of the season, {w} finish in the top 6 in "
                              f"{fs.v('p_top6')} of runs and reach the playoffs (top 10) in {fs.v('p_top10')}.",
                          "p_top6", "p_top10"))
            out.append(_s(fs, f"The 6th-placed team typically ends on about {fs.v('cutline')}, and {w} are "
                              f"projected at {fs.v('proj_points')}.", "cutline", "proj_points"))
        if fs.has("stake_win"):
            out.append(_s(fs, f"Tonight matters: a win lifts the top-6 chance to {fs.v('stake_win')}, "
                              f"a loss drops it to {fs.v('stake_loss')}.", "stake_win", "stake_loss"))
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
            out.append(_s(fs, f"What's at stake: win and the top-6 chance goes to {fs.v('stake_win')}, "
                              f"lose and it's {fs.v('stake_loss')}, a swing of {fs.v('stake_swing')}.",
                          "stake_win", "stake_loss", "stake_swing"))
        if fs.has("prediction"):
            out.append(_s(fs, f"Your call on record: {fs.v('prediction')}.", "prediction"))
        if persona == "buddy":
            out.append("Big one. Bring your voice!")
    elif intent == "bet":
        out.append("I don't give betting tips, but here's what the data model says.")
        if fs.has("p_win_next"):
            out.append(_s(fs, f"The model gives {T} a {fs.v('p_win_next')} chance to win the next game, "
                              f"{fs.v('next_game')}.", "p_win_next", "next_game"))
        out.append(_s(fs, f"Recent form: {fs.v('form5')}.", "form5"))
        if fs.has("opp_form5"):
            out.append(_s(fs, f"Opponent form: {fs.v('opp_form5')}.", "opp_form5"))
        out.append("Model estimates aren't bookmaker odds. If you play, set a budget and keep it fun.")
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
        out.append(_s(fs, f"Season record (W–OTW–OTL–L) is {fs.v('record')} with a goal difference of {fs.v('gd')}.",
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
        parts.append(_s(fs, f"Why it matters: a win takes the top-6 chance to {fs.v('stake_win')}, "
                            f"a loss leaves it at {fs.v('stake_loss')}.", "stake_win", "stake_loss"))
    if fs.has("top_scorer"):
        parts.append(_s(fs, f"Player to watch: {fs.v('top_scorer')}.", "top_scorer"))
    parts.append("That's your brief. Enjoy the game!" if persona == "buddy" else "That's the brief for today.")
    return "\n".join(parts)


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
        out.append("What a night!" if won else "Tough one tonight.")
    out.append(_s(fs, f"Final: {fs.v('final')}, a {fs.v('result')} worth {fs.v('points_earned')} "
                      f"point{'s' if fs.v('points_earned') != '1' else ''}.", "final", "result", "points_earned"))
    if fs.has("star"):
        out.append(_s(fs, f"Star of the night: {fs.v('star')}.", "star"))
    out.append(_s(fs, f"{T} move from {fs.v('rank_before')} to {fs.v('rank_after')} on {fs.v('points_after')} "
                      f"points, with tonight's other games still to finish.",
                  "rank_before", "rank_after", "points_after"))
    out.append(_s(fs, f"Top-6 chance: {fs.v('top6_before')} before the game, {fs.v('top6_after')} now "
                      f"({fs.v('top6_change')}).", "top6_before", "top6_after", "top6_change"))
    if fs.has("prediction"):
        out.append(_s(fs, f"Your prediction ({fs.v('prediction')}): {fs.v('prediction_verdict')}.",
                      "prediction", "prediction_verdict"))
    return " ".join(out)
