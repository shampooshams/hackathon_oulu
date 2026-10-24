"""Kaleva Fan Companion — Streamlit prototype.

Run:  streamlit run app.py
"""
from __future__ import annotations

import base64
import copy
import html
import os
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

from companion.agent import follow_ups, route  # noqa: E402
from companion.companion import Companion  # noqa: E402
from companion.config import FORMATS, LEAGUE, SIMULATIONS, use_league  # noqa: E402
from companion.data.providers import get_provider  # noqa: E402
from companion.facts import add_team_facts, build_team_facts, find_teams, pct, stake_race  # noqa: E402
from companion.live import apply_result, event_facts, postgame_facts, simulate_tonight  # noqa: E402
from companion.llm import explain, get_backend  # noqa: E402
from companion.offline import HOSTS  # noqa: E402
from companion.profile import load_profile, save_profile  # noqa: E402
from companion.render import CSS, THEME_SYNC, THEME_TOGGLE, badges, receipts_rows, to_html  # noqa: E402
from companion.scenarios import simulate  # noqa: E402
from companion.stats import fmt_date, next_game, ordinal, standings  # noqa: E402
from companion.tts import browser_player, gemini_audio  # noqa: E402
from companion.verify import strip_citations  # noqa: E402

st.set_page_config(page_title="Your AI sports assistant", page_icon="🏒", layout="wide")
# Light and dark themes: fans pick in ⋮ → Settings (System follows the device). THEME_SYNC (in the sidebar)
# makes the custom HTML follow. Charts and table colours below are chosen to read well on both.
st.markdown(CSS, unsafe_allow_html=True)
CHART = {"top": "#2f64b0", "mid": "#8cc0ff", "miss": "#8796a8"}
TEAM_TINT = "rgba(252, 209, 22, 0.16)"


# ---------- cached data ----------------------------------------------------
# Live data is re-fetched every few minutes so new results show up without a restart.
REFRESH_MINUTES = int(os.getenv("COMPANION_REFRESH_MINUTES", "10"))


@st.cache_data(show_spinner="Loading league data…", ttl=REFRESH_MINUTES * 60)
def load_snapshot(source: str):
    return get_provider(source).snapshot(), datetime.now(ZoneInfo("Europe/Helsinki"))


@st.cache_data(show_spinner="Simulating the rest of the season…", max_entries=4)
def season_sim(source: str, results_key: str, _snap):
    """Re-simulated only when a result changes (results_key), not on every data refresh."""
    return simulate(_snap)


@st.cache_resource
def llm_backend():
    return get_backend()


# ---------- session --------------------------------------------------------
ss = st.session_state
ss.setdefault("profile", load_profile())
ss.setdefault("chat", [])
ss.setdefault("game", None)
ss.setdefault("podcast", None)
ss.setdefault("sponsor", "Sample Sponsor Oy")
prof = ss.profile


def html_block(markup: str, height: int):
    if hasattr(st, "iframe"):
        st.iframe(markup, height=height)
    else:
        components.html(markup, height=height)


def render_receipts(reply):
    if reply.report.cited_ids or reply.log:
        with st.expander(f"Fact receipts ({len(reply.report.cited_ids)})"):
            rows = receipts_rows(reply)
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            for line in reply.log:
                st.caption(line)
            st.caption("Every number is checked against its cited fact before you see it. "
                       "Sentences without numbers are the companion's opinion.")


def render_reply(reply):
    st.markdown(to_html(reply.text, reply.facts), unsafe_allow_html=True)
    st.markdown(badges(reply), unsafe_allow_html=True)
    if reply.engine.endswith("(fallback)"):
        why = next((l for l in reply.log if l.startswith("AI model unavailable")), "")
        st.caption(f"⚠ {why or 'The AI model could not be reached.'}")
    render_receipts(reply)


def render_podcast(item: dict):
    reply = item["reply"]
    if item.get("audio"):
        st.audio(item["audio"], format="audio/wav")
    else:
        html_block(browser_player(reply.text, "fi-FI" if prof["language"] == "Suomi" else "en-GB"), 52)
        if item.get("audio_note"):
            st.caption(item["audio_note"])
    with st.expander("Script", expanded=False):
        for line in reply.text.splitlines():
            host, _, said = line.partition(":")
            if host.strip() in HOSTS and said:
                st.markdown(f'<div class="script-line"><b>{host.strip()}</b>{to_html(said.strip(), reply.facts)}'
                            f'</div>', unsafe_allow_html=True)
            elif line.strip():
                st.markdown(to_html(line, reply.facts), unsafe_allow_html=True)
    st.markdown(badges(reply), unsafe_allow_html=True)
    if reply.engine.endswith("(fallback)"):
        why = next((l for l in reply.log if l.startswith("AI model unavailable")), "")
        st.caption(f"⚠ {why or 'The AI model could not be reached.'}")
    render_receipts(reply)


def make_podcast(short: bool) -> dict:
    reply = comp.podcast(facts, ss.sponsor, short=short, simulate_error=demo_halluc)
    item = {"role": "assistant", "kind": "podcast", "reply": reply, "audio": None, "audio_note": ""}
    if comp.backend and "Gemini" in comp.backend.name:
        try:
            item["audio"] = gemini_audio(reply.text)
        except Exception as e:  # quota, model name, network: fall back to browser voices
            item["audio_note"] = f"Gemini voices unavailable ({type(e).__name__}), using browser voices."
    return item


# ---------- sport and league data ------------------------------------------
SPORTS = {"Hockey": "🏒 Ice hockey", "Football": "⚽ Football", "Floorball": "🏑 Floorball",
          "Basketball": "🏀 Basketball", "Bandy": "⛸️ Bandy"}
ICON = {"Hockey": "🏒", "Football": "⚽", "Floorball": "🏑", "Basketball": "🏀", "Bandy": "⛸️"}
DEFAULT_TEAM = {"Hockey": "KARPAT", "Football": "ACOULU", "Floorball": "OLS", "Basketball": "KATAJA",
                "Bandy": "OLS"}   # Oulu teams where there is one
@st.cache_data
def hero_image() -> str:
    """The welcome banner photo (AI-generated), inlined so it works without static file serving."""
    return base64.b64encode((Path(__file__).parent / "assets" / "hero.jpg").read_bytes()).decode()


def capabilities(team: str) -> list[tuple[str, str, str]]:
    """What the assistant can do, shown above the stats before the first message."""
    return [   # free features first, the three Premium ones (★) on the second row
        ("💬", "Answers about your team", f"The table, form, home and away, the schedule and top scorers. "
                                          f"Mention another team and I'll compare it with {html.escape(team)}."),
        ("🏟️", "Game night", "Follow tonight's game event by event and see how the table changes."),
        ("✅", "Checked facts", "Every number links to its source and is checked against the data. "
                               "No betting tips."),
        ("📈", "Playoff chances ★", f"I simulate the rest of the season {SIMULATIONS:,} times and tell you what "
                                    "tonight's game means for the race."),
        ("🎙️", "Daily podcast ★", "Two hosts talk through your team's day. Ask for an episode for your "
                                   "commute to work, school or home."),
        ("🔔", "Alerts and predictions ★", "Get warned when your team's chances drop, and save your score "
                                           "prediction for the next game."),
    ]


with st.sidebar:
    st.markdown('<div class="brand">Your AI sports assistant<span class="dot">.</span>'
                '<div class="brand-sub">Personalised for you</div></div>', unsafe_allow_html=True)
    keys = list(SPORTS)
    sport = st.selectbox("Sport", keys, format_func=SPORTS.get,
                         index=keys.index(prof["sport"]) if prof.get("sport") in SPORTS else 0)
if ss.get("sport_shown") not in (None, sport):   # switching sport starts a fresh conversation
    ss.chat, ss.game, ss.podcast = [], None, None
ss.sport_shown = prof["sport"] = sport

# Hockey: real Liiga data (COMPANION_DATA=mock for offline work). Other sports: demo seasons until feeds exist.
source = sport.lower() if sport != "Hockey" else os.getenv("COMPANION_DATA", "liiga").lower()
use_league(FORMATS[source])          # every rule and wording below follows this sport's league
D, P = LEAGUE.direct_spots, LEAGUE.playin_last
try:
    snap, fetched_at = load_snapshot(source)
except Exception as e:  # API unreachable or changed
    st.error(f"Could not load data from the Liiga API: {e}")
    st.caption("Check that this computer or server can reach the Liiga API (try `python probe_api.py`), "
               "then reload the page.")
    st.stop()
results_key = "|".join(f"{g['id']}:{g['home_goals']}-{g['away_goals']}{g['decided']}"
                       for g in snap.games if g["status"] == "final")
season = season_sim(source, results_key, snap)

# ---------- sidebar --------------------------------------------------------
with st.sidebar:
    team_ids = sorted(snap.teams, key=snap.name)
    teams_by_sport = prof.setdefault("teams", {})
    current = teams_by_sport.get(sport) or (prof["team"] if sport == "Hockey" else DEFAULT_TEAM[sport])
    if current not in team_ids:
        current = DEFAULT_TEAM[sport] if DEFAULT_TEAM[sport] in team_ids else team_ids[0]
    teams_by_sport[sport] = st.selectbox("Your team", team_ids, format_func=snap.name,
                                         index=team_ids.index(current), key=f"team_{sport}")
    prof["team"] = teams_by_sport[sport]
    with st.form("personalise"):                     # always open; changes apply when the fan presses Submit
        st.markdown("**Personalise**")
        my_name = st.text_input("Your name", prof.get("name", ""))
        my_language = st.selectbox("Language", ["English", "Suomi"],
                                   index=["English", "Suomi"].index(prof.get("language", "English")))
        my_length = st.select_slider("Answer length", ["short", "normal", "long"],
                                     value=prof.get("length", "normal"))
        my_fan_since = st.text_input("Fan since (year)", prof.get("fan_since", ""))
        roster = [""] + sorted(p["name"] for p in snap.roster(prof["team"]))
        fav = prof.get("fav_player", "")
        my_fav_player = st.selectbox("Favourite player", roster, index=roster.index(fav) if fav in roster else 0)
        if st.form_submit_button("Submit", type="primary", width="stretch"):
            prof.update(name=my_name.strip(), language=my_language, length=my_length,
                        fan_since=my_fan_since.strip(), fav_player=my_fav_player)
            st.success("✓ Submitted")
    save_profile(prof)

    backend = llm_backend()
    with st.expander("Demo controls"):
        use_ai = st.toggle("Use AI model", value=backend is not None, disabled=backend is None)
        st.caption(f"Engine: {backend.name}" if backend else
                   "No AI key found: answers use offline templates. Add GEMINI_API_KEY to the app's secrets.")
        if backend and st.button("Test AI connection"):
            try:
                said = backend.generate("Reply with the single word OK.", [{"role": "user", "content": "Test"}], 20)
                st.success(f"Connected: {backend.name} replied “{said[:40]}”.")
            except Exception as e:
                st.error(f"Not connected: {explain(e)}")
        demo_halluc = st.toggle("Inject a hallucination",
                                help="Corrupts one number in the AI's draft to show the fact checker catching it.")
        st.markdown(
            f"**How it works.** Results come from {snap.source}. Plain code computes the table and "
            f"{SIMULATIONS:,} simulated seasons. Every number becomes a fact with an ID; the AI must cite it, "
            "and a checker blocks any number that doesn't match.")

    components.html(THEME_SYNC, height=0)
    s1, s2 = st.columns([3, 1], vertical_alignment="center")
    s1.caption(f"● {snap.source} · updated {fetched_at:%H:%M}")
    if s2.button("↻", help=f"Refresh now (data refreshes every {REFRESH_MINUTES} min)"):
        load_snapshot.clear()
        st.rerun()

TEAM = prof["team"]
T = snap.name(TEAM)
comp = Companion(backend if use_ai else None, "buddy", prof["length"],
                 "Finnish" if prof["language"] == "Suomi" else "English", prof.get("name", ""))
facts = build_team_facts(snap, TEAM, season, prof)
row = next(r for r in standings(snap) if r.team == TEAM)
ng = next_game(snap, TEAM)
H, A = (snap.name(ng["home"]), snap.name(ng["away"])) if ng else ("", "")
OPP = (A if ng["home"] == TEAM else H) if ng else ""

# ---------- header ---------------------------------------------------------
city = snap.teams[TEAM].get("city")
head, toggle = st.columns([5, 1], vertical_alignment="top")
head.markdown(f'<div class="kicker">{LEAGUE.name}{" · " + html.escape(city) if city else ""}</div>'
              f'<div class="hero">{html.escape(T)}</div>', unsafe_allow_html=True)
with toggle:
    components.html(THEME_TOGGLE, height=42)
if snap.is_mock:
    st.markdown('<div class="notice notice-demo"><span class="notice-label">Demo</span><span>Team names are real '
                'clubs, but all players, scores and results are invented.'
                + (f" There's no {sport.lower()} data feed yet." if sport != "Hockey" else "") + '</span></div>',
                unsafe_allow_html=True)
rows = standings(snap)
gap = rows[D - 1].pts - row.pts
cards = [("Position", ordinal(row.rank), f"{row.gp} games played", None),
         ("Points", str(row.pts), f"In the top {D}" if row.rank <= D else
          f"Level with {ordinal(D)}" if gap == 0 else f"{gap} behind {ordinal(D)}", None),
         (f"Top-{D} chance", pct(season.p_top6[TEAM]),
          f"Playoffs (top {P}): {pct(season.p_top10[TEAM])}" if P > D else LEAGUE.direct_goal.capitalize(),
          season.p_top6[TEAM])]
if ng:
    days = (datetime.fromisoformat(ng["date"]).date() - fetched_at.date()).days
    when = {0: "Today", 1: "Tomorrow"}.get(days, fmt_date(ng["date"]))
    cards.append(("Next game", f"{'vs' if ng['home'] == TEAM else 'at'} {OPP}", f"{when} · {ng['time']}", None))
# A welcome banner and what the assistant can do, always at the top
st.markdown(f'<div class="welcome" style="background-image:url(data:image/jpeg;base64,{hero_image()})">'
            f'<div class="welcome-text"><div class="welcome-title">Hi! I follow {html.escape(T)} for you.</div>'
            '<div class="welcome-sub">Ask me anything, any time. Here\'s what I can do.</div>'
            '<a class="welcome-btn" href="#chat-box" target="_self">💬 Chat with me here</a></div>'
            '<span class="welcome-label">AI-generated image</span></div>', unsafe_allow_html=True)
st.markdown('<div class="cap-grid">' + "".join(
                f'<div class="cap"><div class="cap-icon">{icon}</div><div><b>{title.removesuffix(" ★")}</b>'
                + ('<span class="premium">Premium</span>' if title.endswith("★") else "") +
                f'<div class="cap-text">{text}</div></div></div>' for icon, title, text in capabilities(T))
            + '</div>', unsafe_allow_html=True)
st.markdown('<div class="stat-grid">' + "".join(
    f'<div class="stat"><div class="stat-label">{html.escape(k)}</div>'
    f'<div class="stat-value{" long" if len(v) > 10 else ""}">{html.escape(v)}</div>'
    + (f'<div class="stat-bar"><span style="width:{100 * bar:.0f}%"></span></div>' if bar is not None else "")
    + f'<div class="stat-sub">{html.escape(sub)}</div></div>' for k, v, sub, bar in cards) + "</div>",
    unsafe_allow_html=True)

tab_chat, tab_game, tab_race, tab_pod = st.tabs(["Chat", "Tonight", "Table", "Podcast"])

# ---------- chat (agent) ---------------------------------------------------
def typing(text: str):
    """Show a reply word by word, like someone typing (the fact chips appear once it's done)."""
    for word in text.split(" "):
        yield word + " "
        time.sleep(0.018)


def answer(question: str) -> dict:
    """Route the fan's message to a tool (podcast, alert, prediction) or answer it from the facts."""
    r = route(question, None, T, OPP,  # keyword rules: saves one AI call (and quota) per message
              facts.v("next_game") if facts.has("next_game") else "none")
    if r["tool"] == "podcast":
        return make_podcast(short=False)
    if r["tool"] == "set_alert":
        if r.get("threshold"):
            prof["alerts"]["odds_below"] = int(r["threshold"])
            text = f"Done. I'll alert you if {T}'s top-{D} chance falls below {int(r['threshold'])}%."
        else:
            prof["alerts"]["top6_drop"] = True
            text = f"Done. I'll alert you if {T} drop out of the top {D}."
        save_profile(prof)
        return {"role": "assistant", "kind": "action",
                "content": text + " Alerts are checked after every game (see Tonight)."}
    if r["tool"] == "save_prediction" and ng:
        prof["predictions"][ng["id"]] = {"home": r["home"], "away": r["away"]}
        save_profile(prof)
        return {"role": "assistant", "kind": "action",
                "content": f"Saved your prediction: {H} {r['home']}–{r['away']} {A}. I'll check it after the game."}
    msg_facts = facts
    mentioned = find_teams(snap, question, exclude=TEAM)
    if mentioned:                        # "how about Tappara?": add facts about the teams they named
        msg_facts = copy.deepcopy(facts)
        for other in mentioned:
            add_team_facts(msg_facts, snap, TEAM, other, season)
    history = [{"role": m["role"], "content": m.get("content", "")} for m in ss.chat]
    reply = comp.chat(msg_facts, history, question, simulate_error=demo_halluc)
    return {"role": "assistant", "kind": "chat", "reply": reply, "content": reply.text}


with tab_chat:
    for m in ss.chat:
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else ICON[sport]):
            if m["role"] == "user":
                st.markdown(m["content"])
            elif m["kind"] == "podcast":
                render_podcast(m)
            elif m["kind"] == "action":
                st.markdown(m["content"])
                st.markdown('<span class="badge b-ok">✓ Done</span>', unsafe_allow_html=True)
            else:
                render_reply(m["reply"])

    st.markdown('<div id="chat-box"></div>', unsafe_allow_html=True)   # where "Chat with me here" jumps to
    prompt = st.chat_input(f"Ask your {T} assistant anything…")
    question = prompt or ss.pop("pending", None)
    if question:
        with st.chat_message("user", avatar="🧑"):
            st.markdown(question)
        with st.chat_message("assistant", avatar=ICON[sport]):
            with st.spinner("Thinking…"):
                item = answer(question)
            if item["kind"] != "podcast":
                st.write_stream(typing(strip_citations(item["content"])))
        ss.chat += [{"role": "user", "content": question}, item]
        st.rerun()

    last_q = next((m["content"] for m in reversed(ss.chat) if m["role"] == "user"), None)
    sugg = follow_ups(last_q, OPP, f"Top-{D} race" if P == D else "Playoff chances")
    if not ss.chat:                      # first visit: three questions and one action
        sugg = dict(list(sugg.items())[:3]) | {f"Top-{D} alert": f"Set a top-{D} alert"}
    cols = st.columns(len(sugg))
    for col, (label, q) in zip(cols, sugg.items()):
        if col.button(label, width="stretch", key=f"sugg_{label}"):
            ss.pending = q
            st.rerun()
    if ss.chat and st.button("Clear chat", type="tertiary"):
        ss.chat = []
        st.rerun()

# ---------- tonight --------------------------------------------------------
with tab_game:
    if not ng:
        st.info("No upcoming games in the fixture list.")
    else:
        st_ = season.stakes.get(TEAM)
        if ss.game and ss.game["game"]["id"] != ng["id"]:
            ss.game = None
        left, right = st.columns([1, 1.4], gap="large")
        with left:
            st.markdown(f'<div class="kicker">{fmt_date(ng["date"])} · {ng["time"]}</div>'
                        f'<div class="section-title">{html.escape(H)} vs {html.escape(A)}</div>',
                        unsafe_allow_html=True)
            if st_:
                # Show the race tonight's game can actually move: the top places, or else the playoff line.
                race, win, loss = stake_race(st_)
                st.markdown(f"**What tonight means for {html.escape(T)}**")
                if max(win, loss) < 0.01 or min(win, loss) > 0.99 or abs(win - loss) < 0.01:
                    where = "out of reach" if max(win, loss) < 0.5 else "almost certain"
                    st.caption(f"A {race} finish is {where} either way ({pct(win)}), so tonight's result "
                               f"won't change it much. It's still a chance to get some points on the board.")
                else:
                    st.caption(f"{T}'s chance of finishing {race}, depending on tonight's result "
                               f"(a swing of {round(100 * abs(win - loss))} percentage points):")
                    m1, m2 = st.columns(2)
                    m1.metric(f"If {T} win", pct(win))
                    m2.metric(f"If {T} don't win" if LEAGUE.draws else f"If {T} lose", pct(loss))
            with st.container(border=True):
                st.markdown("**Your prediction**")
                pred = prof["predictions"].get(ng["id"], {"home": 2, "away": 2})
                p1, p2 = st.columns(2)
                ph = p1.number_input(H, 0, 15, int(pred["home"]), key="pred_h")
                pa = p2.number_input(A, 0, 15, int(pred["away"]), key="pred_a")
                if st.button("Save prediction"):
                    prof["predictions"][ng["id"]] = {"home": int(ph), "away": int(pa)}
                    save_profile(prof)
                    st.toast("Prediction saved. Your companion checks it after the game.")
            with st.expander("Alerts"):
                prof["alerts"]["top6_drop"] = st.checkbox(f"Tell me if {T} drop out of the top {D}",
                                                          value=prof["alerts"].get("top6_drop", True))
                prof["alerts"]["odds_below"] = st.slider(f"Tell me if the top-{D} chance falls below (%)", 0, 100,
                                                         int(prof["alerts"].get("odds_below") or 50))
                save_profile(prof)

        with right:
            st.markdown('<div class="kicker">Live preview</div>', unsafe_allow_html=True)
            if ss.game is None:
                st.caption("Plays a simulated version of tonight's game, event by event, then updates the table "
                           "and playoff chances. The real game isn't streamed live yet.")
                with st.expander("Simulation settings"):
                    g1, g2 = st.columns(2)
                    outcome = g1.selectbox("Outcome", ["any", "win", "loss"],
                                           format_func=lambda x: {"any": "Random", "win": f"{T} win",
                                                                  "loss": f"{T} lose"}[x])
                    seed = g2.number_input("Game script #", 1, 999, 1)
                    ai_pings = st.checkbox("AI-written live pings (slower)", value=False, disabled=not comp.backend)
                if st.button("▶ Start preview", type="primary"):
                    game, events = simulate_tonight(snap, TEAM, int(seed), outcome)
                    ss.game = {"game": game, "events": events, "idx": 0, "feed": [], "post": None,
                               "alerts": [], "ai_pings": ai_pings}
                    st.rerun()
            else:
                gs = ss.game

                def finish():
                    after = apply_result(snap, gs["game"], gs["events"])
                    scen_after = simulate(after)
                    pf, alerts = postgame_facts(snap, after, TEAM, gs["game"], season, scen_after, prof)
                    gs["post"] = comp.postgame(pf, T, simulate_error=demo_halluc)
                    gs["alerts"] = [(a, pf) for a in alerts]

                def advance(n: int):
                    while n > 0 and gs["idx"] < len(gs["events"]):
                        ev = gs["events"][gs["idx"]]
                        ef = event_facts(snap, gs["game"], ev)
                        rep = comp.ping(ef, ev, T, use_ai=gs["ai_pings"])
                        cls = ""
                        if ev["type"] == "goal":
                            cls = "goal" if ev["team"] == TEAM else "against"
                        gs["feed"].append((cls, rep, ev))
                        gs["idx"] += 1
                        n -= 1
                    if gs["idx"] >= len(gs["events"]) and gs["post"] is None:
                        with st.spinner("Final whistle. Re-simulating the season…"):
                            finish()

                done = gs["idx"] >= len(gs["events"])
                last = gs["events"][gs["idx"] - 1] if gs["idx"] else None
                status = "Final" if done else f"event {gs['idx']} of {len(gs['events'])}"
                st.markdown(f'<div class="scoreline">{html.escape(H)} <b>{last["home_score"] if last else 0}'
                            f' – {last["away_score"] if last else 0}</b> {html.escape(A)}<span>{status}</span></div>',
                            unsafe_allow_html=True)
                b1, b2, b3 = st.columns(3)
                if b1.button("Next event ▶", disabled=done, width="stretch"):
                    advance(1)
                    st.rerun()
                if b2.button("Skip to final ⏭", disabled=done, width="stretch"):
                    advance(len(gs["events"]))
                    st.rerun()
                if b3.button("Reset", width="stretch"):
                    ss.game = None
                    st.rerun()

                if gs["post"]:
                    for text, pf in gs["alerts"]:
                        st.markdown(f'<div class="ping alert"><div>{to_html(text, pf)}</div></div>', unsafe_allow_html=True)
                    with st.container(border=True):
                        st.markdown("**Post-game recap**")
                        render_reply(gs["post"])
                for cls, rep, ev in reversed(gs["feed"]):
                    st.markdown(f'<div class="ping {cls}"><div>{to_html(rep.text, rep.facts)}</div></div>',
                                unsafe_allow_html=True)

# ---------- table ----------------------------------------------------------
with tab_race:
    st.markdown(f'<div class="kicker">The race</div><div class="section-title">'
                f'{f"Top-{D} race" if P == D else "Playoff race"}</div>',
                unsafe_allow_html=True)
    middle = f", {D + 1}th–{P}th play the {LEAGUE.first_round}" if P > D else ""
    st.caption(f"Top {D} go {LEAGUE.direct_goal}{middle}; the rest {LEAGUE.out_label}. Chances come from "
               f"{season.n:,} simulated seasons: probabilities, not predictions.")
    # Bands of the final table: (name, % column, colour, first place, last place)
    bands = ([(LEAGUE.top_band, f"Top {D} %", CHART["top"], 1, D),
              (LEAGUE.out_band, "Miss %" if LEAGUE.out_band == "Miss" else "Bottom %", CHART["miss"], D + 1,
               len(snap.teams))] if P == D else
             [(LEAGUE.top_band, f"Top {D} %", CHART["top"], 1, D),
              ("First round", f"{D + 1}–{P} %", CHART["mid"], D + 1, P),
              (LEAGUE.out_band, "Miss %", CHART["miss"], P + 1, len(snap.teams))])
    probs = {f"Top {D} %": season.p_top6, f"{D + 1}–{P} %": season.p_playin, "Miss %": season.p_out,
             "Bottom %": season.p_out}
    table = pd.DataFrame([{
        "Pos": r.rank, "Team": r.name, "GP": r.gp, "Pts": r.pts, "GD": r.gd,
        **{col: round(100 * probs[col][r.team]) for _, col, _, _, _ in bands},
        "Proj. pts": round(season.proj_points[r.team]),
    } for r in standings(snap)])
    styled = table.style.apply(
        lambda r: [f"background-color: {TEAM_TINT}; font-weight: 700" if r["Team"] == T else ""] * len(r),
        axis=1)
    st.dataframe(styled, hide_index=True, width="stretch", height=36 * (len(table) + 1) + 3)

    st.markdown(f"#### Where {T} finish")
    dist = season.rank_dist[TEAM]
    chart = pd.DataFrame({"Final position": [ordinal(i + 1) for i in range(len(dist))],
                          **{name: [round(100 * p, 1) if lo <= i + 1 <= hi else 0 for i, p in enumerate(dist)]
                             for name, _, _, lo, hi in bands}})
    st.bar_chart(chart, x="Final position", y=[b[0] for b in bands], y_label="% of simulations",
                 color=[b[2] for b in bands], sort=False)

# ---------- podcast --------------------------------------------------------
with tab_pod:
    st.markdown('<div class="kicker">Today</div><div class="section-title">Your podcast'
                '</div>', unsafe_allow_html=True)
    st.caption(f"{HOSTS[0]} (the fan) and {HOSTS[1]} (the analyst) talk through today's {T} news, written from "
               "the data and fact-checked. The sponsor line is clearly labelled.")
    k1, k2 = st.columns([1, 1])
    length = k1.segmented_control("Length", ["1-minute brief", "Full episode"], default="Full episode")
    k2.text_input("Sponsor (ad slot)", key="sponsor")
    if st.button("🎙 Make today's podcast", type="primary"):
        with st.spinner("Writing, fact-checking and recording…"):
            ss.podcast = make_podcast(short=length == "1-minute brief")
    if ss.podcast:
        render_podcast(ss.podcast)
