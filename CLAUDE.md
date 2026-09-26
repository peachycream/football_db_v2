# CLAUDE.md — football_db_v2

Sole developer: Turon Caine (MFL: Big_T_Caine). **`REBUILD_DESIGN.md` is the contract** — read it before any work; its §10 decisions are settled. `REBUILD_LOG.md` is the per-phase handoff: read it first, update it once per phase.

## Non-negotiable rules (each one exists because v1 broke on it)
1. **No name-based player matching, ever.** Loaders copy the source's own player id. Mapping to `gsis_id` happens only in `player_ids`, by exact key (source-native, id map, jersey bridge, or `identity_overrides.csv` with a reason). A name may reject a candidate, never select one.
2. **One owner per table**, enforced by `registry/sources.yaml`. A second source gets its own table.
3. **Source field names are kept verbatim in `core_*`.** Renaming happens once, in `mart_*` views.
4. **Store counts; compute rates at read time.** Never average a rate: `SUM(rate*w)/SUM(w)`.
5. **`season_type` on every fact row; preseason is never loaded.** Scope comes from `completed_weeks()`; a loader never chooses its own weeks.
6. **Never `INSERT OR REPLACE`.** Delete the scope, then insert, in one transaction, with post-write checks that roll back on failure.
7. **A non-final period is never served from cache**, and a nested-empty payload counts as empty.
8. **Exit 0 is not proof.** Every loader checks field names before writing, plausibility after, and idempotency on re-run.
9. **The DB is rebuildable** from `data/raw/` + code with zero network calls. User-entered state lives in `app_*` tables and is exported before any rebuild.
10. **Apps read `mart_*` only.**
11. **Every loader joins `fdb weekly` in the phase it is written.**

## Environment
- Production: Windows `cmd.exe` — no `&&`, no PowerShell operators.
- Flask/pandas: `"C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"`. Bare `python` is 3.14 with no Flask.
- Secrets in `.env` (gitignored, including `.env.*` copies). Never commit a copy of `.env` under any name.

## Session economics
One phase per session. At every gate, DB write, deploy or decision handed back, say plainly that it is a clean stopping point and stop. v1 is the read-only reference oracle for parity checks — never a data source.
