# Fan Companion (Kaleva Media challenge)

An AI companion that lives a fan's season with them. It is built on three ideas:

1. **Personal and proactive**: it knows your team, your favourite player and your predictions. It pings you live during the game and sends a daily audio brief.
2. **Explains what's at stake**: a season simulator answers questions like "what do we need for a top-6 finish?" and "what does tonight's game change?"
3. **Never lies about numbers (fact receipts)**: every number the AI writes must cite a fact ID. An automatic checker blocks anything that doesn't match the data before the fan sees it.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # optional: add an API key for full AI answers
streamlit run app.py
```

Without an API key, the app uses offline templates. They follow the same fact-citing rules, so the demo always works. Add `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to `.env` for fluent AI answers, personas and Finnish.

Run the reliability tests with `python -m pytest -q`.

## What's in the app

| Tab | What it shows |
|---|---|
| 💬 Companion | Chat in three personas (Superfan buddy, Calm analyst, Bettor's notebook). Every number has a hoverable fact chip and a receipts table. |
| 🏒 Game night | Prediction, alerts, then tonight's game event by event with live pings. At the final whistle, the season is re-simulated: post-game recap, odds shift, prediction verdict and triggered alerts. |
| 📈 Playoff race | Table with top-6, play-in and miss-playoff probabilities for every team, plus your team's finishing-position distribution. |
| 🎧 Daily brief | A 60-second game-day brief with a labelled sponsor slot, read aloud in the browser. |

Sidebar toggle **"Demo: inject a hallucination"**: this corrupts one number in the AI's draft, so judges can watch the checker block it and regenerate the answer.

## How it works

```
League data (mock or Liiga API)
   └─ stats.py        table, form, streaks, head-to-head, scorers   (plain code, no AI)
   └─ scenarios.py    10,000 simulated seasons → playoff odds, stakes of the next game
   └─ facts.py        every number becomes a fact: ID, label, value, source
   └─ companion.py    LLM (or templates) writes in the chosen persona, citing [F12]
   └─ verify.py       every number must match a cited fact → else regenerate → else remove
   └─ app.py          labelled "AI-generated", with receipts
```

**Publishing policy (for the pitch):**
- Data-only text that passes the checker can be published automatically.
- Opinion and banter carry no numbers and are labelled as the companion's voice.
- Anything about people beyond the data (injuries, quotes) isn't generated at all. It would go to an editor.

## Connecting the real Liiga API

The adapter for the Liiga stats API (v1) is in `companion/data/providers.py` (`LiigaApiProvider`). It reads:

| What | Endpoint |
|---|---|
| Teams | `GET /api/v1/teams?season=2027&serie=RUNKOSARJA` |
| Fixtures and results | `GET /api/v1/games/schedule?season=2027&serie=RUNKOSARJA` |
| Goals and penalties | `GET /api/v1/games/{season}/{gameId}` (finished games, cached in `data/cache/`) |
| Official table (for checking) | `GET /api/v1/standings/RUNKOSARJA?season=2027` |

1. In `.env`, set `LIIGA_API_BASE` (default `https://prod.liiga-backend.liiga.fi/stats`), `LIIGA_API_KEY` (sent as the `x-api-key` header) and `LIIGA_SEASON` (the year the season ends: 2026–27 is `2027`). The API is only reachable from the network where its Swagger page opens.
2. Run `python probe_api.py`. It finds the base URL that answers and saves sample responses to `api_samples/`.
3. Run `python check_standings.py`. It compares the table computed from real results with the official Liiga table.
4. Run `streamlit run app.py`. The app uses real Liiga data only; if the API can't be reached it shows the error instead of the app. Set `COMPANION_DATA=mock` in `.env` to work offline with the fictional demo season. Data is re-fetched every 10 minutes (`COMPANION_REFRESH_MINUTES`), and the sidebar has a "Refresh data now" button.

`tests/test_liiga_api.py` checks the mapping against responses shaped like the API docs, including overtime, shootouts and cancelled games.

## Merging with the team

- The whole feature lives in `companion/`, with `app.py` as a thin UI on top.
- If your team has its own frontend or backend, the main entry points are:
  - `build_team_facts(snapshot, team_id, odds, profile)` gives you the facts
  - `Companion(...).chat(facts, history, message)` returns a reply with `.text`, `.report` and `.status`
  - `Companion(...).brief(facts, sponsor)` gives the daily brief
  - `simulate(snapshot)` gives the playoff odds
- If a teammate already pulls Liiga data, share one provider so both of you get the same numbers.

## Demo data

The mock season uses real Liiga club names, with fictional players, scores and results. "Today" is set to 2026-10-24 (`COMPANION_AS_OF`). Regenerate with `python -m companion.data.generate_mock`.

## Ideas for the pitch (not built)

- Group chat mode (Telegram) with a friends' prediction league and a sponsored leaderboard
- Junior and lower-division teams: the same pipeline gives every local team its own companion
- Vertical video: brief script plus stat cards plus voice-over
