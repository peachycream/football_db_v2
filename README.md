# football_db_v2

Fantasy football analytics database, rebuilt from scratch (2016 → present).

- **Spec:** [`REBUILD_DESIGN.md`](REBUILD_DESIGN.md) — architecture, identity model, source-ownership registry, loader contract, phases.
- **Progress log:** [`REBUILD_LOG.md`](REBUILD_LOG.md) — Phase 0 done; next is Phase 1 (identity).

The database is a build artifact: `python -m fdb rebuild` regenerates it from `data/raw/` with no network calls.

## Quick start
```
python -m fdb update nflverse.schedules --apply   # fetch + load the schedule
python -m fdb weeks                               # completed weeks this season
python -m fdb rebuild                             # regenerate the DB from data/raw, offline
python -m fdb weekly [--test-alert]               # the scheduled job
python -m unittest discover -s tests -t .         # tests
```
Stdlib only so far (Python 3.11+). On Windows use the 3.13 interpreter by full path (see `CLAUDE.md`).
