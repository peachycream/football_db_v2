# PHASE15_PROMPT.md — IDP prospect model (college -> NFL fantasy), DRAFT PLAN

**Status:** DRAFT 2026-10-30, not started. Read `REBUILD_DESIGN.md` and the latest `REBUILD_LOG.md` section first. One phase per session; each sub-phase below ends at a gate and a stop point.

## Why this is worth building
A web search (2026-10-30) found PFF's LB / EDGE / DT prospect models (proprietary, inputs: pass-rush grades, win rate, pressure rate, draft capital, athleticism, competition level) and 4for4's 2021 EDGE / DL studies (draft capital dominates; college TFL/G -> NFL TFL/G r 0.51; speed score r 0.34). No published backtest, no DB model, no open model. v2 already holds most of what is needed: Phase 14 loaded `core_cfbd_*` and `core_pff_ncaa_*` (2025-2026), Phase 7b built the NFL-side IDP outcome machinery.

## What already exists (do not rebuild)
| Need | Existing |
|---|---|
| NFL outcome (IDP points by exact id) | `core_mfl_player_scores` (only 2025+), `core_pff_defense_week`, `core_pbp` tackle/sack attribution, `mart_idp_week`, `mart_idp_expected_*` |
| League scoring | `core_mfl_rules` (catch-all, `fantasy.scoring`) |
| NFL identity | `players`, `player_ids` (gsis_id; nflverse `players.csv` carries `pff_id`, `pfr_id`, `espn_id`, `otc_id`) |
| College production loaders | `fdb/loaders/cfbd.py`, `fdb/loaders/pff_ncaa.py`; `core_cfbd_player_season/usage/roster`, `core_pff_ncaa_{defense,pass_rush,...}_season`. **Seasons 2025-2026 only** |
| College -> person bridge | `devy_identity` / `devy_pff_identity`: manual, cell-keyed, ~93 players. Not usable at scale |

## Hard problems (decide before building)
1. **College -> NFL id bridge (Rule 1).** No name matching. Candidate exact keys, to be probed in 15a:
   - nflverse `draft_picks` carries `pfr_player_id`, `gsis_id`, `cfb_player_id` (a sports-reference college id) and `college`. If `cfb_player_id` is populated, that is an exact bridge for every drafted player.
   - PFF NCAA player id -> NFL `pff_id`: PFF generally keeps one id across college and NFL (the spec notes NFL/NCAA ids "legitimately differ" for some, so measure, don't assume).
   - CFBD athlete id: probably no native bridge. Fallback = `identity_overrides.csv`-style reviewed file, candidates only, as Phase 14 did. Acceptable for a few hundred rows, not thousands.
   - Undrafted players: out of scope for v1 of the model (state this in the report). Train and score drafted players only.
2. **Backfill cost.** CFBD quota is 1,000 calls/month; the loaders are whole-season-per-call, so 2016-2025 is ~30 calls: cheap. PFF NCAA is one call per facet-season: ~50 reads. Check the PFF college facets for history depth (does PFF NCAA go back to 2016?).
3. **Outcome definition.** MFL scores only exist 2025+, so the training label cannot be MFL. Use PFF-defense / pbp raw counts x the league scoring rules at read time (Rule 4: counts stored, rates computed on read). Label candidates: top-12 / top-24 position finish at least once in years 1-3; mean PPG in years 1-3 with a snap floor. Settle with Turon before 15c.
4. **Position mapping.** PFF NFL positions (DI/ED/LB/CB/S) vs college positions (CFBD/PFF NCAA) vs MFL (DT/DE/LB/DB). Use the draft table's / players' own position fields; do not infer position from stat lines. Hybrid EDGE/LB players (Jalon Walker type) are the known failure; report them rather than hide them.
5. **Small samples.** ~10 draft classes x ~30 LB and ~30 EDGE per class is a few hundred rows per position. Prefer regularized logistic / ordinal and a draft-capital-only baseline over anything flexible. No claim of accuracy without out-of-time validation.

## Sub-phases

### 15a — Bridge probe (read-only, no DB writes)
- Fetch nflverse `draft_picks` and `combine` release assets into `data/raw/` via the loader framework (new owners: `core_nflverse_draft_picks`, `core_nflverse_combine`; one owner per table).
- Measure, per draft class 2017-2025 and position group (LB, EDGE, DT, S, CB): coverage of `gsis_id`, `pfr_player_id`, `cfb_player_id`, combine join by `pfr_id`, PFF NCAA id availability.
- **Gate:** a written coverage table in the log and a go/no-go on the bridge. Floor: >= 90% of drafted defenders 2017-2025 reach a college production row by exact key. If below, stop and ask Turon whether to add a reviewed-candidates file.

### 15b — College history backfill
- Run existing `cfbd.*` and `pff.ncaa_*` loaders for 2016-2024 (check `contracts/` field lists still match older seasons; PFF/CFBD era changes are the usual trap).
- Add whatever CFBD / PFF NCAA facet the model needs and is missing (e.g. PFF NCAA coverage summary for safeties, if it exists).
- **Gate:** per-season row counts, plausibility bounds (games <= 17, tackles per game sane), idempotent re-run, `fdb weekly` join (Rule 11: set `weekly = true` only for in-season refresh; backfill seasons are final and cached), offline `fdb rebuild` x2 identical.

### 15c — NFL outcome table
- Builder `idp_prospect.outcomes` -> `mart_idp_prospect_outcome`: per gsis_id, years 1-3 IDP points under catch-all scoring from counts, snaps, position finish. Seasons 2016-2025 (rookie classes 2016-2023 have >= 2 observed years).
- Right-censoring is explicit: classes with < 3 observed years carry `years_observed`.
- **Gate:** reconcile against `core_mfl_player_scores` for 2025 (the one season with reported truth), rank correlation >= 0.95 per position.

### 15d — Features mart
- `mart_idp_prospect_features` per (gsis_id, final college season): draft round / overall pick, age at draft (from `players.birth_date`), height/weight, combine 40 / 10-yd / broad / vertical, speed score computed at read time, college TFL/G, sacks/G, tackles/G, PFF pass-rush win rate and pressure rate (counts, ratios at read time, snap-weighted when pooling seasons), run-defense grade, coverage snaps/targets, breakout age proxy, FBS conference tier.
- Missing combine data stays NULL with an indicator column; no imputation in the mart.
- **Gate:** no leakage test (every feature's season <= draft year - 1), join coverage per position reported, `mart_` read-only.

### 15e — Model + backtest
- Position-specific models (LB, EDGE, DT, S; CB reported but not recommended per PFF). Baseline 0 = draft pick only. Baseline 1 = pick + age + athletic. Model = baseline 1 + college production rates.
- Validation: **rolling-origin by draft class** (train classes < N, predict N), 2020-2023 as test years. No random k-fold.
- Metrics: AUC and Brier for top-12/top-24, Spearman of predicted vs realized year 1-3 PPG, calibration table, and **lift over the draft-pick-only baseline** with bootstrap CI. Report feature importance with coefficient signs.
- **Gate (decided now, before looking):** the model must beat the draft-pick-only baseline on pooled out-of-time Spearman with a bootstrap CI that excludes zero, per position it is shipped for. If not, ship nothing for that position and say so; do not tune until it passes.

### 15f — Score the current class + page
- Score 2026 / 2027 draft-eligible defenders from `core_cfbd_*` + `core_pff_ncaa_*` (extends the `/devy/` page: new `mart_idp_prospect_scores`, shown for DL/LB/DB). Labelled with model version, backtest metrics and position coverage. Unbridged players are scored from college features only, flagged "no draft capital yet".
- **Gate:** page renders, `fdb rebuild` x2 identical, tests added.

## Open decisions for Turon
1. Outcome label (top-12 vs top-24 vs PPG) and whether years 1-3 or best of 1-3.
2. Whether a reviewed-candidates file is acceptable if the exact-key bridge covers < 90%.
3. Include CB / S, or LB / EDGE / DT only (PFF's own models skip DB).
4. Budget: confirm CFBD calls (~30) and PFF NCAA reads (~50) for the backfill.
5. Phase ordering: this does not touch the open items (Discord webhook, Trayanum/Salter overrides, sack-tile gate); run it whenever you choose.

---

## 15a result (2026-10-30, cloud container, read-only; nflverse assets only)

Probe: `draft_picks.csv`, `combine.csv`, `players.csv` from nflverse releases, joined by exact id only. Script kept outside the repo (scratchpad `probe15a.py`); no DB writes, no names in any join. Egress limits: PFF, CFBD and the v2 DB are not reachable/present in the container, so the college half could NOT be measured here.

**NFL side: solid.** 1,148 drafted defenders 2017-2025 (`side = D`).
- `gsis_id` 1,145/1,148 (99.7%); the 3 missing are rounds 4/7 with 0 games. `pfr_player_id` 100%. No duplicate `gsis_id` / `pfr_player_id` / `cfb_player_id`.
- Cross-source agreement: `draft_picks.gsis_id` vs `players.pfr_id` -> `gsis_id`: **1,145 agree, 0 disagree**.
- `players.pff_id` present for 99.7% of them, every position group, every season.
- Combine (exact `pfr_id` join): 70-90% of players by season; **40-yd time only 48-75%** (2025 lowest, probably early/in-progress or pro-day-only), so athletic features will be NULL for a quarter to half of rows. Combine `draft_year` agrees with `draft_picks.season` on every joined row. The 17 duplicated combine `pfr_id`s are all old (2000s) re-entries and none touch 2017+, but the loader should still refuse duplicate keys.
- Position vocabulary in `draft_picks`: DE, DT, DL, NT, OLB, ILB, LB, CB, S, SAF, DB. `SAF` (30) and `DB` (133) are not separable into S/CB without a rule; EDGE vs LB for `OLB`/`DE` is ambiguous. Grouping must be decided (use `players.position`/PFF NFL position as the model's own field, not names).

**College side: the finding that changes the plan.** `cfb_player_id` is a **Sports-Reference slug** (94-99% populated, unique). Neither CFBD nor PFF NCAA, the two college sources v2 owns, carries it. So it is **not** a bridge to our college stats. It would only help if we loaded Sports Reference CFB, which is a scrape, not an API; not proposed.

Real candidate bridges, untested:
1. **PFF NCAA `player_id` = NFL `pff_id`?** `players.pff_id` exists for 99.7% of drafted defenders, so if PFF keeps one id across college and NFL this is an exact bridge for nearly everyone. `core_pff_ncaa_*` also has `draft_season`/`franchise_id`, which can validate it (drafted college rows should carry the draft year and team of the matching NFL player). Design 3.3 says PFF NFL/NCAA ids "legitimately differ" in some cases, so measure it. **Needs the v2 DB (Windows) or a PFF NCAA call.**
2. **CFBD athlete id:** no native NFL key found in nflverse (`players.csv` has esb/nfl/pfr/pff/otc/espn/smart ids only). CFBD stays reachable only through the reviewed-candidates file or via PFF.

**Gate status: NOT MET, not failed.** The >= 90% college-production reach cannot be computed without PFF NCAA history, which is also not loaded for 2016-2024 (15b). Next action, on Windows: load PFF NCAA 2016-2024 (15b step), then measure `pff_ncaa.player_id` == `players.pff_id` coverage for the drafted-defender list above, and check `draft_season`/`franchise_id` agreement as the exact-key validation. If it clears 90%, the plan stands with PFF as the only college source for the model (CFBD becomes a cross-check). If not, ask Turon about a reviewed-candidates file.

**Decisions this adds:** (6) Accept PFF-only college features (PFF has pass-rush win rate / pressure / coverage, which the research favors over CFBD's box score), with CFBD for TFL/G only if it can be bridged. (7) Since only 48-75% have a 40 time, athletic score needs a missing-indicator and a rule for imputing nothing (RAS from a different source is out of scope).
