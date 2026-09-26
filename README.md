# football_db_v2

Fantasy football analytics database, rebuilt from scratch (2016 → present).

- **Spec:** [`REBUILD_DESIGN.md`](REBUILD_DESIGN.md) — architecture, identity model, source-ownership registry, loader contract, phases.
- **Progress log:** `REBUILD_LOG.md` (created in Phase 0).
- **Next step:** Phase 0 — see [`PHASE0_PROMPT.md`](PHASE0_PROMPT.md).

The database is a build artifact: `python -m fdb rebuild` regenerates it from `data/raw/` with no network calls.
