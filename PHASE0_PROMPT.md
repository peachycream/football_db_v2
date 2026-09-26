# Phase 0 kickoff prompt — football_db_v2

Paste the block below as the first message of a new session with this repository attached.

---

You are starting Phase 0 of `football_db_v2`, a from-scratch rebuild of my fantasy football database. The full spec is `REBUILD_DESIGN.md` in this repo root. Read it in full before writing code. It is the contract. Do not re-litigate decisions in its §10.

**Phase 0 deliverables (spec §2, §5, §7, §8):**
1. Repo skeleton: `fdb/` package with a `python -m fdb` CLI; `schema/` numbered SQL files; `registry/sources.yaml`; `data/raw/` (gitignored); `tests/`; `.gitignore` covering `*.db`, `data/raw/`, `.env` **and `.env.*`**.
2. The loader framework with the five-step contract (fetch → validate_source → load → check → idempotency), a `raw_fetch_log` manifest, `load_log`, and framework-owned `is_final`. Loaders must not be able to choose their own scope.
3. `core_schedule` 2016–2026 from nflverse (`nflreadpy.load_schedules`), plus the `teams` normalisation table. `completed_weeks(season)` derived from it: a week counts only when every game is final and at least 24 hours have passed.
4. `fdb rebuild`: empty DB → schema → replay loaders from `data/raw/` → marts → checks, with **zero network calls**.
5. `fdb weekly` wired end to end with nothing but the schedule loader in it: `PIPELINE_STATUS.json` (starting as `running`, alerting on a stale `running`), and a Discord alert via `OPS_DISCORD_WEBHOOK` with `--test-alert`.
6. `REBUILD_LOG.md` as the per-phase handoff log.

**Gate (write the result to `REBUILD_LOG.md`):**
- `fdb rebuild` run twice gives identical content hashes.
- `completed_weeks(2026)` matches the real 2026 schedule as of today.
- A fetch for a week that isn't final is not served from cache on the next run (unit test).
- The nested-empty payload `{"x": []}` is treated as empty (unit test).

**Environment:** the production machine is Windows `cmd.exe` (no `&&`). Flask/pandas scripts run under `C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe`; bare `python` is 3.14 with no Flask. Keep the framework stdlib + `nflreadpy` + `pandas` only.

**Rules:** no name-based player matching anywhere; no `INSERT OR REPLACE`; one owner per table; source field names kept verbatim in `core_*` tables. Stop at the gate and report. Don't start Phase 1.
