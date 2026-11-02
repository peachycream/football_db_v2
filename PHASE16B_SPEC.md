# PHASE16B_SPEC.md — the next-season outlook: mart (Stage 1) and dashboard tile (Stage 2) (DRAFT, awaiting Turon's approval; nothing below has been built)

**Status:** drafted 2026-11-01 after Phase 16a passed its gate at DT, S and CB and failed at DE and LB (`REBUILD_LOG.md`, `PHASE16A_SPEC.md`, `238ce9d`/`3c616da`/`150c17c`). Once approved this file is committed UNCHANGED before any code. Stage 1 ends at a clean stopping point; Stage 2 starts only after Turon has seen Stage 1's numbers and a mockup of the tile.

## What is built, and what is not claimed
Stage 1 turns the 16a model into a rebuildable mart. Stage 2 shows it in the existing IDP dashboard. Claimed: the ranking of defenders within DT, S and CB by predicted points next season, from the gate-passing model. **Not claimed:** probabilities (top-12 / top-24 calibration was never tested), point intervals, DE or LB outlooks (the gate failed; they stay on last year's points), or anything about rookies (15f stays off).

## Model (frozen: the 16a PRIMARY model, per position group DT, S, CB only)
- Same population, features 1-8 with their indicators, scoring (`fdb.idp_prospect._season_points`, catch-all rules of LEAGUE), median fill, standardisation, ridge, alpha by leave-one-transition-out over {3, 10, 30, 100}, target `points_next` (0 if no row next season).
- **Origin rule, same as 16a:** the outlook for season N is trained only on candidates from seasons N' < N whose next season is closed by the end of N. So the mart holds a pseudo-out-of-time outlook for every N from 2021 on (identical to the 16a rolling-origin predictions) and the live outlook for the newest closed season (now N = 2025, predicting 2026).
- **Ridge in numpy, not sklearn.** `fdb` does not import sklearn today; the weekly job and `fdb rebuild` should not depend on it. The closed form (centred X and y, standardised, unpenalised intercept) is parity-tested against sklearn's `Ridge` to 1e-8.

## Stage 1 — mart and builder (no UI)
Builder `idp_outlook.build` (`fdb/idp_outlook.py`), registry rows, migration `053`, runs after `idp_prospect.outcomes` in registry order. Tables:
| Table | Grain | Holds |
|---|---|---|
| `mart_idp_outlook` | one row per candidate player-season (N from 2021, snaps >= 300, groups DE, DT, LB, S, CB) | gsis_id, season_n, season_next, position_group, points_n, games_n, snaps_n, points_prev and games_prev (NULL if none), et_gap and es_gap (counts, NULL if none), age_next (years at 1 Sep of N+1), draft_year, `model` ('ridge16a' for DT/S/CB, NULL for DE/LB), `pred_points_next` (NULL when no model), `rank_pred` and `rank_last` (within group among the season's candidates; ties share the best rank), `points_next_actual` (NULL until season N+1 is closed) |
| `mart_idp_outlook_model` | (season_n, position_group) | n_train, first and last training N, alpha, intercept, and per-feature coefficient, median, mean and scale (JSON text) |
| `mart_idp_outlook_exit` | (season_n, position_group, age_band) | n and n_zero over the training candidates (age bands <25, 25-27, 28-30, 31+); the rate is computed at read time, and a cell with n < 25 is not shown |
Counts are stored, rates computed at read time (CLAUDE.md rule 4). Only closed seasons are used; a season in progress is never an N or a target (rule 7). Delete-scope-then-insert in one transaction with the checks below rolling back on failure (rule 6). No name is read; the key is gsis_id.

**Checks (a failure rolls the build back and is a named exception, never a looser tolerance):**
1. **Parity with the backtest.** For N = 2021..2024 and DT, S, CB the builder's predictions equal `ops/phase16a_backtest.py`'s `PRIMARY` predictions to 1e-6 (row for row, same candidates), and the Spearman of `pred_points_next` against `points_next_actual` pooled over N = 2021-2024 reproduces the 16a values (DT 0.555, S 0.499, CB 0.498 to three decimals). If either fails, nothing ships.
2. One row per (gsis_id, season_n); `season_n` closed; `season_next` = N + 1; `rank_pred` only where `model` is set; candidates have snaps >= 300; `points_next_actual` is NULL exactly when N + 1 is not closed.
3. Predictions finite and within the training targets' observed range widened by 25%; each model group has at least 60 candidates in the newest N and at least 400 training rows.
4. Idempotent re-run, `fdb rebuild` x2 identical, 0 network calls, full test suite green, `fdb weekly` runs the builder.

**Frozen prospective record.** The live outlook for N = 2025 (predicting 2026) is committed to `REBUILD_LOG.md` (its rank list and the model coefficients) the day it is built. When the 2026 season is closed, one report-only evaluation runs the 16a primary measure on those frozen 2025 predictions as a fifth test year. It is not a new gate and is not re-run or tuned; the 2026 season is not evaluated while it is in progress.

## Stage 2 — dashboard tile (after Stage 1 and a mockup are approved)
- Endpoint `/api/dashboard/outlook?season=&bucket=` in `app/dashboard.py`, reading `mart_idp_outlook`, `mart_idp_outlook_exit` and the profile mart only (rule 10). Returns for each player: outlook rank and last-year rank, rank change, last year's points, age, the exit band's n and zero count.
- UI: a sortable table in the existing IDP dashboard, DT/S/CB with the outlook rank, DE/LB with last year's rank only and a "no outlook model for this position" note. A fixed one-line caption on the page: "Ranking only; the model beat last year's points at DT, S and CB (Phase 16a); no probabilities."
- A mockup built from real Stage 1 rows is shown to Turon before any frontend code. Frontend build via the existing `frontend/copy-to-flask.mjs`; endpoint tests; the page is checked in the browser at desktop and phone width.

## Risks stated now
1. **The season in progress.** The newest N (2025) predicts 2026, which is half played. The rank is a pre-season expectation, not a rest-of-season forecast, and the page says so.
2. **Expected-stat rates.** The expected-tackle and expected-sack cells were fitted on seasons 2016-2024 (2025 held out), so the gap features of N <= 2024 are in-sample for the rates and N = 2025's are not. The 16a lift does not depend on them (P-E added about 0.02-0.03 at most), but the live N = 2025 features are slightly differently distributed.
3. **Age bands are descriptive.** Zero-next-season rates come from training counts and are not a tested model; thin cells are hidden.
4. **A gate-passing result at three positions can still be noise at one of them.** Treat each position separately on the frozen 2026 evaluation.

## Not in this spec
DE and LB models; probabilities or intervals; rookies and the prospect page; weekly in-season forecasts; league-specific scoring beyond LEAGUE's catch-all rules; push alerts (no webhook); any change to the prospect or devy features.

## Work, if approved
**Stage 1:** commit this spec unchanged; builder and migration `053`; registry rows; tests (ridge parity, builder checks, scope rules); build and the parity checks; snapshot the DB first; `fdb rebuild` x2; log the frozen N = 2025 outlook. Stop and report. **Stage 2** only after Turon's go-ahead: mockup, endpoint, tile, tests, browser check.
