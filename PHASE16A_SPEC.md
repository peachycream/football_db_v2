# PHASE16A_SPEC.md — forward model: predict next season's IDP points from this season (DRAFT, awaiting Turon's approval; nothing below has been run)

**Status:** drafted 2026-11-01 after the four prospect attempts (15e, 15e-2, 15e-3, 15e-4) all failed against the draft slot (`REBUILD_LOG.md`). Once approved this file is committed UNCHANGED before any 16a number is computed. A failed result is reported as failed; no edits after the first run; another idea is another spec. This is a different question from the prospect model (veterans with NFL history, not rookies), so it is Phase 16a and does not reopen 15f.

## Question
For an NFL defender who played at least 300 snaps in season N, which of this season's numbers predict his fantasy points in season N+1 better than simply ranking by this season's points? In particular, do two things that persistence ignores carry information: **regression to the mean** (actual tackles and sacks versus the NFL expected-tackle and expected-sack marts) and **age and experience**.

## Why this has more power than the prospect model
About 520 defenders a season clear 300 snaps (seasons 2016-2025). Nine transitions (N = 2016..2024) and four test years give roughly 400 test player-seasons per position, against 50-90 for the prospect backtests, so a lift of about 0.05 is detectable. The baseline (last year's points) is also strong, so a pass is not assured.

## Data (nothing new to load; read-only)
- Points, games, snaps and position group per player-season: `fdb.idp_prospect._season_points` unchanged (REG season, `mart_player_allowed_week`, the catch-all rules of LEAGUE via `catch_all_rules`, group = the group with the most snaps). Same scoring as the outcome mart.
- Birth date and draft year: `mart_player_profile` (3,323 of 3,323 defenders with PFF seasons have a birth date).
- Expected tackles and expected sacks: `mart_idp_expected_tackles_week` and `mart_idp_expected_sacks_week`, REG weeks of season N, summed per `gsis_id`.
- Join key: `gsis_id` everywhere (the key `_season_points` returns). A row without a `gsis_id` is dropped and counted. No name is read.

## Population and target
- Candidates: player-seasons (N, player) with `snaps >= 300` in season N, N = 2016..2024, groups EDGE, DT, LB, S, CB.
- Target: `points_next` = total league points in season N+1 (REG). A player with no row in N+1 (retired, cut, injured all year, no snaps) has `points_next = 0`. This keeps injury, benching and exit in the outcome, because those are the risks a dynasty manager actually carries. 2025 is the last target year (closed).
- Folds: rolling origin by season. Test N in {2021, 2022, 2023, 2024}; each is trained on candidates from transitions with N' < N (all earlier transitions, targets known by the end of season N). Pooled out of time per position.

## Features (fixed here; all known by the end of season N; per-game rates are computed at read time)
1. `ppg_N` — points per game in N.
2. `log_snaps_N` — log of snaps in N.
3. `games_N` — games played in N.
4. `age` — years from birth date to 1 September of N+1.
5. `exp_yrs` — N+1 minus draft year (NULL if no draft year) plus indicator `has_draft_year`.
6. `ppg_prev` — points per game in N-1 (NULL if no games) plus indicator `has_prev`.
7. `et_gap_pg` — (actual tackles minus expected tackles in N) per game, run and pass summed, plus indicator `has_et`.
8. `es_gap_pg` — (sacks minus expected sacks in N) per game, plus indicator `has_es`.
Missing -> training median plus its indicator. Ridge on standardised features; alpha chosen by leave-one-transition-out inside the training transitions over {3, 10, 30, 100} (squared error); target `points_next`.

## Models
- **B0** = rank by `points_N` (total points in N).
- **PRIMARY** = features 1-8.
- **P-S** = features 1-3 only (a ridge version of persistence), **P-A** = P-S + 4-5 (age and experience), **P-E** = P-S + 7-8 (expected-minus-actual). All descriptive.
- **B1** = rank by `ppg_N` (descriptive).

## Primary test and ship rule
Per position: Spearman(PRIMARY) - Spearman(B0) against `points_next` on pooled out-of-time candidates. Players recur across test years, so the paired bootstrap resamples **players** (all of a player's test rows together): 2,000 draws, seed 16, two-sided p. Holm across the five positions. A position ships only if the point estimate is > 0 AND the Holm-adjusted p < 0.05; otherwise nothing ships for it. Nothing is tuned and nothing is re-run.

## Reported descriptively (not gates)
- P-S, P-A, P-E lifts over B0 with intervals (which block carries it); B1.
- Top-12 and top-24 finish in N+1 (finish within the position group among players with games > 0, as the outcome mart): AUC of PRIMARY versus B0, and Brier of a logistic version with the same features.
- The same Spearman against `ppg_next` for candidates who reached 300 snaps again in N+1 (the survivors), to separate "who keeps playing" from "how well he produces".
- Share of candidates with zero points next season, by position and age band.
- Standardised coefficients and their signs per position (age curve, regression of the tackle and sack gaps).

## Risks stated now
1. **A strong baseline.** Last year's points are a good predictor; ridge on a handful of features may add nothing and a simple fit can be worse than ranking by last year's points. That is a valid result and is reported as failed.
2. **Role changes the data cannot see.** Free-agent moves, coaching changes and injuries after the season are not features; they appear as noise in the target. Feature 3 (games) carries last year's injuries only.
3. **Test years overlap in players.** The player-cluster bootstrap handles this; the stated power ("about 0.05") is approximate.
4. **Expected-tackle and expected-sack marts begin where on-field and pass-rush data begin.** Coverage per position and season is reported; missing is filled with the training median plus an indicator.

## Not in this spec
Weekly or in-season forecasts; rookies and the prospect model (15f stays off); scoring or ranking the current roster; any app tile; any change to the DB (no loader, migration or rebuild). If a position ships, a later phase would put the read-only outlook in `mart_*` and the app; that is its own spec.

## Work, if approved
1. Commit this spec unchanged. 2. `ops/phase16a_backtest.py` (read-only, imports `_season_points` and `catch_all_rules`), committed before it is run. 3. One run, seed 16. 4. Result, descriptive tables and decisions in `REBUILD_LOG.md`; the 550-test suite unchanged.
