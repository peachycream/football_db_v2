# football_db_v2

Fantasy football analytics database, rebuilt from scratch (2016 → present).

- **Spec:** [`REBUILD_DESIGN.md`](REBUILD_DESIGN.md) — architecture, identity model, source-ownership registry, loader contract, phases.
- **Progress log:** [`REBUILD_LOG.md`](REBUILD_LOG.md) — Phases 0–7b done (expected sacks pending by decision); next is Phase 8 (cutover).

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

## Operations (since Phase 8, 2026-09-29)
v2 is the live system. Two Windows Task Scheduler tasks, both running as the logged-in user:

| Task | When | Runs | Log |
|---|---|---|---|
| `FootballDB v2 Weekly` | Wednesday 05:00, catches up if missed (StartWhenAvailable), 3 h limit | `ops\weekly.bat` → `python -m fdb weekly` (3.13 by full path) | `data\logs\weekly.log`, `PIPELINE_STATUS.json` |
| `FootballDB v2 App` | at logon | `ops\start_app.bat` → the web app on http://127.0.0.1:5000/ | `data\logs\app.log` |

Ops alerts go to Discord only once `OPS_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...` is in `.env`; then run `python -m fdb weekly --test-alert` to confirm.

**v1 is archived:** its four data-writing tasks (`FootballDB Weekly Capture All`, `FootballDB Matchup Refresh`, `FootballDB Weekly NFL Capture`, `FootballDB Weekly Env Capture`) are **disabled, not deleted**. v1's scouting, media and digest tasks were left as they were. To roll back to v1 (PowerShell):
```
Disable-ScheduledTask -TaskName 'FootballDB v2 Weekly'; Disable-ScheduledTask -TaskName 'FootballDB v2 App'
'FootballDB Weekly Capture All','FootballDB Matchup Refresh','FootballDB Weekly NFL Capture','FootballDB Weekly Env Capture' | ForEach-Object { Enable-ScheduledTask -TaskName $_ }
```
