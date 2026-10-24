# Data contract

Everything downstream reads these shapes. A data source only needs to produce them.

## Team
```json
{"id": "KARPAT", "name": "Kärpät", "city": "Oulu",
 "roster": [{"name": "Player Name", "weight": 1.0}]}
```
`roster` is optional; it is only used to simulate games in the demo.

## Game
```json
{"id": "G151", "round": 15, "date": "2026-10-24", "time": "18:30",
 "home": "KARPAT", "away": "ILVES",
 "status": "final" | "scheduled",
 "home_goals": 3, "away_goals": 2,
 "decided": "REG" | "OT" | "SO"}
```
For scheduled games, `home_goals`, `away_goals` and `decided` are `null`. An OT or shootout winner's +1 goal is included in the final score.

## Event (one item of a game's feed, in order)
```json
{"game_id": "G151", "seq": 4, "type": "goal" | "penalty" | "period_end" | "game_end",
 "period": 1 | 2 | 3 | "OT" | "SO" | null, "clock": "13:58",
 "team": "KARPAT" | null, "player": "Name" | null, "assists": ["Name"],
 "detail": "2 min, tripping", "home_score": 1, "away_score": 0}
```
`home_score` and `away_score` are the score after the event.

## Snapshot
`Snapshot(source, is_mock, as_of, teams: {id: Team}, games: [Game], events: {game_id: [Event]})`
