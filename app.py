"""Kaleva Fan Companion — Streamlit prototype.

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

from companion.agent import route  # noqa: E402
from companion.companion import Companion  # noqa: E402
from companion.config import LEAGUE, SIMULATIONS  # noqa: E402
from companion.data.providers import get_provider  # noqa: E402
from companion.facts import build_team_facts, pct  # noqa: E402
from companion.live import apply_result, event_facts, postgame_facts, simulate_tonight  # noqa: E402
from companion.llm import get_backend  # noqa: E402
from companion.offline import HOSTS  # noqa: E402
from companion.profile import load_profile, save_profile  # noqa: E402
from companion.render import CSS, badges, receipts_rows, to_html  # noqa: E402
from companion.scenarios import simulate  # noqa: E402
from companion.stats import fmt_date, next_game, ordinal, standings  # noqa: E402
from companion.tts import browser_player, gemini_audio  # noqa: E402

st.set_page_config(page_title="Fan Companion · Kaleva Media", page_icon="🏒", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
D, P = LEAGUE.direct_spots, LEAGUE.playin_last


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


# ---------- league data ----------------------------------------------------
# Real Liiga data only. COMPANION_DATA=mock is kept for offline development and tests.
source = os.getenv("COMPANION_DATA", "liiga").lower()
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
    st.markdown('<div class="brand"><span class="brand-mark">↗</span><span>FAN<span class="brand-thin">'
                'COMPANION</span><span class="dot">.</span></span></div>', unsafe_allow_html=True)

    team_ids = sorted(snap.teams, key=snap.name)
    prof["team"] = st.selectbox("Your team", team_ids, format_func=snap.name,
                                index=team_ids.index(prof["team"]) if prof["team"] in team_ids else 0)
    with st.expander("Personalise"):
        prof["name"] = st.text_input("Your name", prof.get("name", ""))
        prof["language"] = st.selectbox("Language", ["English", "Suomi"],
                                        index=["English", "Suomi"].index(prof.get("language", "English")))
        prof["length"] = st.select_slider("Answer length", ["short", "normal", "long"],
                                          value=prof.get("length", "normal"))
        prof["fan_since"] = st.text_input("Fan since (year)", prof.get("fan_since", ""))
        roster = [""] + sorted(p["name"] for p in snap.roster(prof["team"]))
        fav = prof.get("fav_player", "")
        prof["fav_player"] = st.selectbox("Favourite player", roster, index=roster.index(fav) if fav in roster else 0)
    save_profile(prof)

    backend = llm_backend()
    with st.expander("Demo controls"):
        use_ai = st.toggle("Use AI model", value=backend is not None, disabled=backend is None)
        st.caption(f"Engine: {backend.name}" if backend else
                   "No AI key found: answers use offline templates. Add GEMINI_API_KEY to the app's secrets.")
        demo_halluc = st.toggle("Inject a hallucination",
                                help="Corrupts one number in the AI's draft to show the fact checker catching it.")
        st.markdown(
            "**How it works.** Results come from the Liiga API. Plain code computes the table and "
            f"{SIMULATIONS:,} simulated seasons. Every number becomes a fact with an ID; the AI must cite it, "
            "and a checker blocks any number that doesn't match.")

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
st.markdown(f'<div class="kicker">Your team companion</div>'
            f'<div class="hero">{html.escape(T)} <em>companion.</em></div>', unsafe_allow_html=True)
if snap.is_mock:
    st.markdown('<div class="demo">ⓘ Demo data: team names are real Liiga clubs, but all players, scores and '
                'results are fictional.</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Position", ordinal(row.rank), help=f"{row.gp} games played")
c2.metric("Points", row.pts)
c3.metric(f"Top-{D} chance", pct(season.p_top6[TEAM]),
          help=f"Top {D} go straight to the quarter-finals. Chance of making the playoffs (top {P}): "
               f"{pct(season.p_top10[TEAM])}")
if ng:
    c4.metric(f"Next: {'vs' if ng['home'] == TEAM else 'at'} {OPP}", fmt_date(ng["date"]), help=ng["time"])

tab_chat, tab_game, tab_race, tab_pod = st.tabs(["Chat", "Tonight", "Table", "Podcast"])

# ---------- chat (agent) ---------------------------------------------------
with tab_chat:
    for m in ss.chat:
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🏒"):
            if m["role"] == "user":
                st.markdown(m["content"])
            elif m["kind"] == "podcast":
                render_podcast(m)
            elif m["kind"] == "action":
                st.markdown(m["content"])
                st.markdown('<span class="badge b-ok">✓ Done</span>', unsafe_allow_html=True)
            else:
                render_reply(m["reply"])

    if not ss.chat:
        st.caption(f"Ask anything about {T}, or ask me to do something: make today's podcast, "
                   f"save your prediction, set an alert.")
    sugg = ["What are our playoff chances?", "What's at stake tonight?", "Make today's podcast",
            f"Set a top-{D} alert"]
    cols = st.columns(len(sugg))
    for col, q in zip(cols, sugg):
        if col.button(q, width="stretch"):
            ss.pending = q
    prompt = st.chat_input(f"Ask or tell your {T} companion…")
    question = prompt or ss.pop("pending", None)
    if question:
        ss.chat.append({"role": "user", "content": question})
        with st.spinner("On it…"):
            r = route(question, comp.backend, T, OPP, facts.v("next_game") if facts.has("next_game") else "none")
            if r["tool"] == "podcast":
                item = make_podcast(short=False)
            elif r["tool"] == "set_alert":
                if r.get("threshold"):
                    prof["alerts"]["odds_below"] = int(r["threshold"])
                    text = f"Done. I'll alert you if {T}'s top-{D} chance falls below {int(r['threshold'])}%."
                else:
                    prof["alerts"]["top6_drop"] = True
                    text = f"Done. I'll alert you if {T} drop out of the top {D}."
                save_profile(prof)
                item = {"role": "assistant", "kind": "action", "content": text + " Alerts are checked after "
                        "every game (see Tonight)."}
            elif r["tool"] == "save_prediction" and ng:
                prof["predictions"][ng["id"]] = {"home": r["home"], "away": r["away"]}
                save_profile(prof)
                item = {"role": "assistant", "kind": "action",
                        "content": f"Saved your prediction: {H} {r['home']}–{r['away']} {A}. "
                                   f"I'll check it after the game."}
            else:
                history = [{"role": m["role"], "content": m.get("content") or m["reply"].text}
                           for m in ss.chat[:-1]]
                reply = comp.chat(facts, history, question, simulate_error=demo_halluc)
                item = {"role": "assistant", "kind": "chat", "reply": reply}
            item.setdefault("content", item["reply"].text if "reply" in item else "")
        ss.chat.append(item)
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
                m1, m2 = st.columns(2)
                m1.metric(f"Top-{D} if they win", pct(st_["top6_if_win"]))
                m2.metric(f"Top-{D} if they lose", pct(st_["top6_if_loss"]))
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
                        st.markdown(f'<div class="ping alert">{to_html(text, pf)}</div>', unsafe_allow_html=True)
                    with st.container(border=True):
                        st.markdown("**Post-game recap**")
                        render_reply(gs["post"])
                for cls, rep, ev in reversed(gs["feed"]):
                    st.markdown(f'<div class="ping {cls}">{to_html(rep.text, rep.facts)}</div>',
                                unsafe_allow_html=True)

# ---------- table ----------------------------------------------------------
with tab_race:
    st.markdown('<div class="kicker">The race</div><div class="section-title">Playoff race'
                '<span class="dot">.</span></div>', unsafe_allow_html=True)
    st.caption(f"Top {D} go straight to the quarter-finals, {D + 1}th–{P}th play the first playoff round. "
               f"Chances come from {season.n:,} simulated seasons: probabilities, not predictions.")
    table = pd.DataFrame([{
        "Pos": r.rank, "Team": r.name, "GP": r.gp, "Pts": r.pts, "GD": r.gd,
        f"Top {D} %": round(100 * season.p_top6[r.team]),
        f"{D + 1}–{P} %": round(100 * season.p_playin[r.team]),
        "Miss %": round(100 * season.p_out[r.team]),
        "Proj. pts": round(season.proj_points[r.team]),
    } for r in standings(snap)])
    styled = table.style.apply(
        lambda r: ["background-color: rgba(211,250,91,.16); font-weight: 700" if r["Team"] == T else ""] * len(r),
        axis=1)
    st.dataframe(styled, hide_index=True, width="stretch", height=36 * (len(table) + 1) + 3)

    st.markdown(f"#### Where {T} finish")
    dist = season.rank_dist[TEAM]
    chart = pd.DataFrame({
        "Final position": [ordinal(i + 1) for i in range(len(dist))],
        "Quarter-final": [round(100 * p, 1) if i < D else 0 for i, p in enumerate(dist)],
        "First round": [round(100 * p, 1) if D <= i < P else 0 for i, p in enumerate(dist)],
        "Miss": [round(100 * p, 1) if i >= P else 0 for i, p in enumerate(dist)],
    })
    st.bar_chart(chart, x="Final position", y=["Quarter-final", "First round", "Miss"], y_label="% of simulations",
                 color=["#d3fa5b", "#ff9b63", "#6b7b8b"], sort=False)

# ---------- podcast --------------------------------------------------------
with tab_pod:
    st.markdown('<div class="kicker">Today</div><div class="section-title">Your podcast'
                '<span class="dot">.</span></div>', unsafe_allow_html=True)
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
