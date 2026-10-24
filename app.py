"""Kaleva Fan Companion — Streamlit prototype.

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

from companion.companion import PERSONAS, Companion  # noqa: E402
from companion.config import LEAGUE, SIMULATIONS  # noqa: E402
from companion.data.providers import get_provider  # noqa: E402
from companion.facts import build_team_facts, pct  # noqa: E402
from companion.live import apply_result, event_facts, postgame_facts, simulate_tonight  # noqa: E402
from companion.llm import get_backend  # noqa: E402
from companion.profile import load_profile, save_profile  # noqa: E402
from companion.render import CSS, badges, receipts_rows, to_html  # noqa: E402
from companion.scenarios import simulate  # noqa: E402
from companion.stats import fmt_date, next_game, ordinal, standings  # noqa: E402
from companion.verify import strip_citations  # noqa: E402

st.set_page_config(page_title="Fan Companion · Kaleva Media", page_icon="🏒", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


# ---------- cached data ----------------------------------------------------
# Live data is re-fetched every few minutes so new results show up without a restart.
REFRESH_MINUTES = int(os.getenv("COMPANION_REFRESH_MINUTES", "10"))


@st.cache_data(show_spinner="Loading league data…", ttl=REFRESH_MINUTES * 60)
def load_snapshot(source: str):
    return get_provider(source).snapshot(), datetime.now(ZoneInfo("Europe/Helsinki"))


@st.cache_data(show_spinner="Simulating the rest of the season…", max_entries=4)
def season_odds(source: str, results_key: str, _snap):
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
ss.setdefault("brief", None)
prof = ss.profile


def render_reply(reply, receipts: bool = True):
    st.markdown(to_html(reply.text, reply.facts), unsafe_allow_html=True)
    st.markdown(badges(reply), unsafe_allow_html=True)
    if receipts and (reply.report.cited_ids or reply.log):
        with st.expander(f"🧾 Fact receipts ({len(reply.report.cited_ids)})"):
            rows = receipts_rows(reply)
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            for line in reply.log:
                st.caption(line)
            st.caption("Every number above is checked against the cited fact before it is shown. "
                       "Sentences without numbers are the companion's opinion.")


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
odds = season_odds(source, results_key, snap)

# ---------- sidebar --------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">↗</span><span>FAN<span class="brand-thin">'
                'COMPANION</span><span class="dot">.</span></span></div>', unsafe_allow_html=True)
    st.caption(f"Kaleva Media · AI sports companion prototype · Data: {snap.source}, "
               f"updated {fetched_at:%H:%M} (every {REFRESH_MINUTES} min)")
    if st.button("↻ Refresh data now", width="stretch"):
        load_snapshot.clear()
        st.rerun()

    team_ids = sorted(snap.teams, key=snap.name)
    prof["name"] = st.text_input("Your name", prof.get("name", ""))
    prof["team"] = st.selectbox("Favourite team", team_ids, format_func=snap.name,
                                index=team_ids.index(prof["team"]) if prof["team"] in team_ids else 0)
    persona_keys = list(PERSONAS)
    prof["persona"] = st.selectbox("Companion style", persona_keys, format_func=lambda k: PERSONAS[k][0],
                                   index=persona_keys.index(prof.get("persona", "buddy")))
    prof["length"] = st.select_slider("Answer length", ["short", "normal", "long"], value=prof.get("length", "normal"))
    prof["language"] = st.selectbox("Language", ["English", "Suomi"],
                                    index=["English", "Suomi"].index(prof.get("language", "English")))
    with st.expander("About you (the companion remembers)"):
        prof["fan_since"] = st.text_input("Fan since (year)", prof.get("fan_since", ""))
        roster = [""] + sorted(p["name"] for p in snap.roster(prof["team"]))
        fav = prof.get("fav_player", "")
        prof["fav_player"] = st.selectbox("Favourite player", roster, index=roster.index(fav) if fav in roster else 0)
    save_profile(prof)

    st.divider()
    backend = llm_backend()
    use_ai = st.toggle("Use AI model", value=backend is not None, disabled=backend is None)
    if backend is None:
        st.caption("No API key found, so answers use offline templates. Add GEMINI_API_KEY, "
                   "ANTHROPIC_API_KEY or OPENAI_API_KEY to `.env` for full AI answers.")
    else:
        st.caption(f"Engine: {backend.name}")
    if prof["language"] == "Suomi" and not (backend and use_ai):
        st.caption("Finnish answers need the AI model; templates are English only.")
    demo_halluc = st.toggle("Demo: inject a hallucination",
                            help="Corrupts one number in the AI's draft to show the fact checker catching it.")

    with st.expander("How it works"):
        st.markdown(
            "1. **Data**: results and fixtures from the league feed.\n"
            "2. **Stats and simulation**: plain code computes the table, form and "
            f"{SIMULATIONS:,} simulated seasons. No AI here.\n"
            "3. **Facts**: every number gets an ID and a source.\n"
            "4. **AI writer**: writes in the chosen persona and must cite fact IDs.\n"
            "5. **Fact check**: every number is matched to its cited fact. Failures are "
            "regenerated or removed before the fan sees them.\n"
            "6. **Label**: everything is marked AI-generated, with receipts.")

TEAM = prof["team"]
T = snap.name(TEAM)
comp = Companion(backend if use_ai else None, prof["persona"], prof["length"],
                 "Finnish" if prof["language"] == "Suomi" else "English", prof.get("name", ""))
facts = build_team_facts(snap, TEAM, odds, prof)
row = next(r for r in standings(snap) if r.team == TEAM)
ng = next_game(snap, TEAM)

# ---------- header ---------------------------------------------------------
st.markdown(f'<div class="kicker">Your team companion</div>'
            f'<div class="hero">{html.escape(T)} <em>companion.</em></div>'
            f'<div class="hero-sub">Live pings, what is at stake tonight and a playoff race that updates after '
            f'every game. Every number comes with a receipt.</div>', unsafe_allow_html=True)
if snap.is_mock:
    st.markdown('<div class="demo">ⓘ Demo data: team names are real Liiga clubs, but all players, scores and '
                'results are fictional.</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Position", ordinal(row.rank), help=f"{row.gp} games played")
c2.metric("Points", row.pts)
c3.metric("Top-6 chance", pct(odds.p_top6[TEAM]))
st_ = odds.stakes.get(TEAM)
if ng and st_:
    opp = snap.name(ng["away"] if ng["home"] == TEAM else ng["home"])
    swing = round(100 * st_["top6_if_win"]) - round(100 * st_["top6_if_loss"])
    c4.metric(f"Next: {'vs' if ng['home'] == TEAM else 'at'} {opp}", fmt_date(ng["date"]),
              help=f"Top-6 chance swings by {swing} percentage points on this game")

tab_chat, tab_game, tab_race, tab_brief = st.tabs(["💬 Companion", "🏒 Game night", "📈 Playoff race",
                                                    "🎧 Daily brief"])

# ---------- chat -----------------------------------------------------------
with tab_chat:
    if not ss.chat:
        st.caption(f"Your {PERSONAS[prof['persona']][0].lower()} for {T}. It answers only from league data "
                   "and shows a receipt for every number.")
    for m in ss.chat:
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🏒"):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                render_reply(m["reply"])

    sugg = ["What are our playoff chances?", "What's at stake tonight?", "How's our form?",
            "Who's our top scorer?", "Should I bet on tonight's game?"]
    cols = st.columns(len(sugg))
    for col, q in zip(cols, sugg):
        if col.button(q, width="stretch"):
            ss.pending = q
    prompt = st.chat_input(f"Ask about {T}…")
    question = prompt or ss.pop("pending", None)
    if question:
        history = [{"role": m["role"], "content": m["content"]} for m in ss.chat]
        with st.spinner("Checking the data…"):
            reply = comp.chat(facts, history, question, simulate_error=demo_halluc)
        ss.chat.append({"role": "user", "content": question})
        ss.chat.append({"role": "assistant", "content": reply.text, "reply": reply})
        st.rerun()
    if ss.chat and st.button("Clear chat"):
        ss.chat = []
        st.rerun()

# ---------- game night -----------------------------------------------------
with tab_game:
    if not ng:
        st.info("No upcoming games in the fixture list.")
    else:
        H, A = snap.name(ng["home"]), snap.name(ng["away"])
        if ss.game and ss.game["game"]["id"] != ng["id"]:
            ss.game = None
        left, right = st.columns([1, 1.4], gap="large")
        with left:
            st.markdown('<div class="kicker">Tonight</div>', unsafe_allow_html=True)
            st.markdown(f"### {H} vs {A}")
            st.caption(f"{fmt_date(ng['date'])} · {ng['time']}")
            if st_:
                m1, m2 = st.columns(2)
                m1.metric("Top-6 if they win", pct(st_["top6_if_win"]))
                m2.metric("Top-6 if they lose", pct(st_["top6_if_loss"]))

            st.markdown("**Your prediction**")
            pred = prof["predictions"].get(ng["id"], {"home": 2, "away": 2})
            p1, p2 = st.columns(2)
            ph = p1.number_input(H, 0, 15, int(pred["home"]), key="pred_h")
            pa = p2.number_input(A, 0, 15, int(pred["away"]), key="pred_a")
            if st.button("Save prediction"):
                prof["predictions"][ng["id"]] = {"home": int(ph), "away": int(pa)}
                save_profile(prof)
                st.success("Saved. Your companion will check it after the game.")

            st.markdown("**Alerts**")
            prof["alerts"]["top6_drop"] = st.checkbox(f"Tell me if {T} drop out of the top 6",
                                                      value=prof["alerts"].get("top6_drop", True))
            prof["alerts"]["odds_below"] = st.slider("Tell me if the top-6 chance falls below (%)", 0, 100,
                                                     int(prof["alerts"].get("odds_below") or 50))
            save_profile(prof)

        with right:
            st.markdown('<div class="kicker">Live</div>', unsafe_allow_html=True)
            st.markdown("### Live companion")
            if ss.game is None:
                st.caption("Plays tonight's game event by event, then updates the table and playoff odds. "
                           "With mock data the game is simulated; with the live API it follows the real feed.")
                g1, g2 = st.columns(2)
                outcome = g1.selectbox("Demo outcome", ["any", "win", "loss"],
                                       format_func=lambda x: {"any": "Random", "win": f"{T} win",
                                                              "loss": f"{T} lose"}[x])
                seed = g2.number_input("Game script #", 1, 999, 1)
                ai_pings = st.checkbox("AI-written live pings (slower)", value=False, disabled=not comp.backend)
                if st.button("▶ Start game", type="primary"):
                    game, events = simulate_tonight(snap, TEAM, int(seed), outcome)
                    ss.game = {"game": game, "events": events, "idx": 0, "feed": [], "post": None,
                               "alerts": [], "ai_pings": ai_pings}
                    st.rerun()
            else:
                gs = ss.game

                def finish():
                    after = apply_result(snap, gs["game"], gs["events"])
                    scen_after = simulate(after)
                    pf, alerts = postgame_facts(snap, after, TEAM, gs["game"], odds, scen_after, prof)
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
                last = gs["events"][gs["idx"] - 1] if gs["idx"] else None
                st.markdown(f"**{H} {last['home_score'] if last else 0} – {last['away_score'] if last else 0} {A}**"
                            f"  ·  event {gs['idx']}/{len(gs['events'])}")

                if gs["post"]:
                    for text, pf in gs["alerts"]:
                        st.markdown(f'<div class="ping alert">{to_html(text, pf)}</div>', unsafe_allow_html=True)
                    with st.container(border=True):
                        st.markdown("**Post-game recap**")
                        render_reply(gs["post"])
                for cls, rep, ev in reversed(gs["feed"]):
                    st.markdown(f'<div class="ping {cls}">{to_html(rep.text, rep.facts)}</div>',
                                unsafe_allow_html=True)

# ---------- playoff race ---------------------------------------------------
with tab_race:
    st.markdown('<div class="kicker">The race</div><div class="section-title">Playoff race'
                '<span class="dot">.</span></div>', unsafe_allow_html=True)
    st.caption(f"{odds.n:,} simulated seasons of the remaining fixtures. Team strength comes from goals for "
               "and against, pulled toward the league average, with extra uncertainty. These are "
               "probabilities, not predictions.")
    table = pd.DataFrame([{
        "Pos": r.rank, "Team": r.name, "GP": r.gp, "Pts": r.pts, "GD": r.gd,
        f"Top {LEAGUE.direct_spots} %": round(100 * odds.p_top6[r.team]),
        "Play-in %": round(100 * odds.p_playin[r.team]),
        "Miss %": round(100 * odds.p_out[r.team]),
        "Proj. pts": round(odds.proj_points[r.team]),
    } for r in standings(snap)])
    styled = table.style.apply(
        lambda r: ["background-color: rgba(211,250,91,.16); font-weight: 700" if r["Team"] == T else ""] * len(r),
        axis=1)
    st.dataframe(styled, hide_index=True, width="stretch", height=600)

    st.markdown(f"#### Where {T} finish")
    dist = odds.rank_dist[TEAM]
    chart = pd.DataFrame({
        "Final position": [ordinal(i + 1) for i in range(len(dist))],
        "Top 6": [round(100 * p, 1) if i < LEAGUE.direct_spots else 0 for i, p in enumerate(dist)],
        "Play-in": [round(100 * p, 1) if LEAGUE.direct_spots <= i < LEAGUE.playin_last else 0
                    for i, p in enumerate(dist)],
        "Miss": [round(100 * p, 1) if i >= LEAGUE.playin_last else 0 for i, p in enumerate(dist)],
    })
    st.bar_chart(chart, x="Final position", y=["Top 6", "Play-in", "Miss"], y_label="% of simulations",
                 color=["#d3fa5b", "#ff9b63", "#6b7b8b"], sort=False)
    st.caption(f"The 6th-placed team typically finishes on about {round(odds.cutline_median)} points "
               f"(middle half of simulations: {round(odds.cutline_range[0])}–{round(odds.cutline_range[1])}).")

# ---------- daily brief ----------------------------------------------------
with tab_brief:
    st.markdown('<div class="kicker">Game day</div><div class="section-title">Your daily audio brief'
                '<span class="dot">.</span></div>', unsafe_allow_html=True)
    st.caption("A personal 60-second game-day brief, written from the data, fact-checked and read aloud. "
               "The ad slot is clearly labelled and kept apart from the facts.")
    sponsor = st.text_input("Sponsored by (ad slot)", "Sample Sponsor Oy")
    if st.button("Generate today's brief", type="primary"):
        with st.spinner("Writing and checking your brief…"):
            ss.brief = comp.brief(facts, sponsor, simulate_error=demo_halluc)
    if ss.brief:
        render_reply(ss.brief)
        spoken = strip_citations(ss.brief.text).replace("[Ad]", "Advertisement.").replace("*", "").replace("_", "")
        lang = "fi-FI" if prof["language"] == "Suomi" else "en-GB"
        payload = json.dumps(spoken).replace("</", "<\\/")
        player = f"""
<div style="font-family:Arial,Helvetica,sans-serif;color:#f0f4f5">
 <button id="play" style="padding:.55em 1.1em;border-radius:6px;border:0;background:#d3fa5b;color:#122014;
   font-weight:800;cursor:pointer">▶ Play brief</button>
 <button id="stop" style="padding:.55em 1.1em;border-radius:6px;border:1px solid #3a4652;background:#202b36;
   color:#f0f4f5;cursor:pointer;margin-left:.4em">■ Stop</button>
 <span style="font-size:12px;color:#9ba7b4;margin-left:.6em">Browser voice for the demo; swap in a TTS API for production.</span>
</div>
<script>
 const text = {payload};
 document.getElementById('play').onclick = () => {{
   speechSynthesis.cancel();
   const u = new SpeechSynthesisUtterance(text); u.lang = '{lang}'; u.rate = 1.03;
   speechSynthesis.speak(u);
 }};
 document.getElementById('stop').onclick = () => speechSynthesis.cancel();
</script>"""
        # brief text is JSON-escaped above, so it can't break out of the script
        if hasattr(st, "iframe"):
            st.iframe(player, height=60)
        else:
            components.html(player, height=60)
