# football_db_v2

Fantasy football analytics database, rebuilt from scratch (2016 → present).

- **Spec:** [`REBUILD_DESIGN.md`](REBUILD_DESIGN.md) — architecture, identity model, source-ownership registry, loader contract, phases.
- **Progress log:** [`REBUILD_LOG.md`](REBUILD_LOG.md) — Phases 0–7a done; next is Phase 7b (expected tackles/sacks model).

The database is a build artifact: `python -m fdb rebuild` regenerates it from `data/raw/` with no network calls.

## Quick start
```
python -m fdb update nflverse.schedules --apply   # fetch + load the schedule
python -m fdb weeks                               # completed weeks this season
python -m fdb identity --apply                    # rebuild players / player_ids
python -m fdb reconcile --season 2024             # cross-source agreement checks
python -m fdb rebuild                             # regenerate the DB from data/raw, offline
python -m fdb weekly [--test-alert]               # the scheduled job
python -m unittest discover -s tests -t .         # tests
python -m app                                     # web app (Flask): http://127.0.0.1:5001/ownership/
                                                  #   /viz/player  /viz/offense  /viz/defense  /matchups/  (v1's React pages)
python -m fdb parity-ownership --v1 <v1 db> --explain   # Phase 3 gate vs the v1 oracle
```
Fantasy leagues in scope and "which franchise is mine": [`config/my_franchises.toml`](config/my_franchises.toml).
MFL credentials (`MFL_USERNAME`, `MFL_PASSWORD`), `PFF_API_KEY` and `FTN_API_KEY` live in `.env` (gitignored).
Loaders are stdlib only (Python 3.11+): every nflverse asset is CSV/CSV.gz, so no pyarrow. The app needs Flask. On Windows use the 3.13 interpreter by full path (see `CLAUDE.md`).
