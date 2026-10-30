# Phase 15a kickoff (Windows) — finish the bridge probe: PFF NCAA id vs NFL `pff_id`

> Written 2026-10-30. Run LOCALLY on Windows (the cloud container cannot reach PFF/CFBD and has no DB). To restart in a new session, paste everything below the line.
> Branch with the plan and the cloud half of 15a: `claude/idp-prospect-phase15-plan` (`PHASE15_PROMPT.md`). Pull it first.

---

You are continuing **Phase 15 (IDP prospect model), sub-phase 15a**, of `football_db_v2`. Read `CLAUDE.md`, `REBUILD_DESIGN.md`, the latest `REBUILD_LOG.md` section, then **`PHASE15_PROMPT.md` in full, including its "15a result" section**. They are the contract. Do not redo the cloud half.

## 0. Environment (Windows `cmd.exe`)
- No `&&`, no PowerShell operators. One command per line.
- Interpreter by full path: `"C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"` (bare `python` is 3.14 without Flask).
- Repo: `C:\Users\k-ble\Desktop\Documents\GitHub\football_db_v2`. v1 oracle (read-only, not needed here): `C:\Users\k-ble\Desktop\football_db`.
- `.env` already holds `PFF_API_KEY` and `CFB_API_KEY`. Never print values, never commit a copy of `.env` under any name.
- First:
  ```
  git fetch origin claude/idp-prospect-phase15-plan
  git checkout claude/idp-prospect-phase15-plan
  "C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe" -m unittest discover -s tests -t .
  ```
  Tests must pass before any change. Take a DB snapshot before the first write (`database\pre_phase15a_<date>.db`, same habit as earlier phases).

## 1. What 15a still has to answer (one question)
**Does PFF NCAA `player_id` equal the NFL `pff_id` for drafted defenders?** If yes, PFF is an exact bridge from college production to `gsis_id`. The cloud half already showed `players.pff_id` is present for 99.7% of the 1,148 defenders drafted 2017–2025, and that `cfb_player_id` (Sports-Reference slug) is **not** a bridge to anything v2 owns.

Rule 1 applies: the bridge is an exact id comparison. A name may be printed in a report to help Turon read it; it may never select or confirm a match.

## 2. Steps
1. **Probe one old season before loading anything.** Call the PFF NCAA defense facet for 2019 (one read) through `fdb/pff.py` and compare its field names with `contracts/pff.ncaa_defense_season.fields` (recorded from 2025). A missing field fails the load by design; a new field warns. Do the same for pass rush. Report any era drift before going further. (NFL PFF had identical columns 2016 vs 2025; college is untested.)
2. **Check history depth.** Find the earliest season for which PFF NCAA returns defense rows. If it starts later than 2016, the training window shrinks accordingly; record the real start.
3. **Widen the loaders' `season_range`** in `fdb/loaders/pff_ncaa.py` (currently `(2025, 2026)`) to the real start through 2026. Change nothing else in the framework. Finality is already by season (`raw_is_final`: season < current season).
4. **Load PFF NCAA defense + pass rush only** for the new seasons (these are the two facets the IDP model needs; the other three belong to 15b if wanted):
   ```
   "C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe" -m fdb update pff.ncaa_defense_season --apply
   "C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe" -m fdb update pff.ncaa_pass_rush_season --apply
   ```
   Run `fdb update <loader>` (dry-run) first. Expect ~1 read per facet-season (~20 reads). Then `fdb check` each loader (idempotent). Update `registry/sources.toml` `seasons =` for the two tables.
5. **Load the nflverse draft and combine tables** as new core tables (one owner each; new files `fdb/loaders/nflverse_draft.py`, schema numbers after the latest in `schema/`):
   - `core_nflverse_draft_picks` from release `draft_picks/draft_picks.csv`; `core_nflverse_combine` from `combine/combine.csv`. Snapshot grain, never final, subclass `SnapshotCsvLoader` like `nflverse_players.py`.
   - Source field names verbatim (Rule 3). Record contracts from the live file.
   - Checks: reject duplicate `pfr_player_id` / `gsis_id` / `cfb_player_id` in draft_picks for 2017+; reject duplicate `pfr_id` within a combine season; combine `draft_year` equals draft_picks `season` on the exact `pfr_id` join (0 violations measured in the cloud). Combine has 17 duplicated `pfr_id`s in the 2000s — scope the check to 2016+ or name them as errata; do not loosen it.
   - Join `fdb weekly` (Rule 11) with `weekly = true`.
6. **Measure the bridge (read-only SQL / script, kept outside the repo or in `ops/`):**
   - Population: `core_nflverse_draft_picks` where `side = 'D'` and `season` 2017–2025 (1,148 rows in the cloud run). Join to `core_nflverse_players` by `gsis_id` to get `pff_id`.
   - Join to `core_pff_ncaa_defense_season` on `CAST(pff_ncaa.player_id AS TEXT) = CAST(players.pff_id AS TEXT)`.
   - Report per draft class and position group: drafted defenders; with an NCAA row for **any** season; with an NCAA row in the season before the draft (the model's feature season); both facets.
   - **Exact-key validation, no names:** for every joined row, PFF NCAA `draft_season` (when set) must equal `draft_picks.season`. Count agree / disagree / unset. A disagreement is the signal that the two PFF id spaces differ for that player; list each by id and season.
   - Check the reverse: does any PFF NCAA `player_id` in 2016+ match one NFL `pff_id` that belongs to a **different** `gsis_id` than a drafted one it should be? (i.e. count NCAA ids that collide with a non-drafted NFL human). Zero is the expectation.
   - Also report for the same population: combine join by `pfr_id` (expect 70–90%) and 40-yd presence (expect 48–75%).
7. **Verdict** against the plan's floor: **≥ 90% of drafted defenders 2017–2025 reach a college production row by exact key**, with 0 `draft_season` disagreements unexplained.
   - Clears: PFF is the college source; record it, and stop.
   - Below 90%: do not add a name-based fallback. Write the shortfall by class/position and ask Turon whether a reviewed-candidates file (candidates only, his approval is the exact key, like `data/devy_review.csv`) is acceptable.

## 3. Gate for this session
- New tables loaded, idempotent, in `fdb weekly`; `registry/sources.toml` updated; contracts recorded from live responses.
- `fdb rebuild` twice → identical content hash, 0 network calls. Snapshot taken first. **Check the exit code of the rebuild itself, not of `tail`** (the 2026-10-14 mistake in the log).
- Unit tests for the new loader (offline fixtures) and for the era-drift check; full suite passes.
- A "Phase 15a" section in `REBUILD_LOG.md` with the coverage table, the `draft_season` agreement counts, the PFF NCAA start season, the verdict, and the open items carried forward (Discord webhook; Trayanum/Salter overrides; sack-tile gate).

## 4. Rules that bite here
- No name-based matching, ever. Loaders copy the source's own id; mapping happens only in `player_ids`/by exact key. The bridge here is a *measurement*, not yet a stored mapping. If it passes, the stored mapping (a builder, not a loader) is 15d's job; do not write one now.
- One owner per table. Source names verbatim in `core_*`. Counts stored, rates at read time.
- A check that fails on real data gets a named exception with a reason, never a looser tolerance.
- A non-final period is never served from cache; nested-empty counts as empty (already enforced by the framework).
- Exit 0 is not proof.
- One phase per session. This session ends at the 15a gate. Say plainly that it is a clean stopping point and stop. **Do not start 15b (the full college backfill) or any modelling.**

## 5. Carried decisions still open for Turon (ask only if the verdict needs them)
1. Outcome label: top-12 vs top-24 vs PPG over years 1–3.
2. Reviewed-candidates file acceptable if the exact-key bridge is < 90%?
3. Include CB/S or only LB/EDGE/DT.
4. PFF-only college features acceptable (CFBD as a cross-check only unless it can be bridged).
5. How to treat missing 40-yd times (missing-indicator, no imputation).
