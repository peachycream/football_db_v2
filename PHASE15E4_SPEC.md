# PHASE15E4_SPEC.md — fourth IDP prospect attempt: predict playing time (Stage 1) (DRAFT, awaiting Turon's approval; nothing below has been run)

**Status:** drafted 2026-11-01 after 15e, 15e-2 and 15e-3 all failed their gates (`REBUILD_LOG.md`). Once approved this file is committed UNCHANGED before any 15e-4 number is computed. A failed result is reported as failed; no edits after the first run; another idea is a fifth spec.

## What changed since 15e-3
Three attempts to beat the draft slot at ranking `ppg3` (pooled points per game, years 1-3, snap floor 300) failed at every position. The 15e-2 role diagnostic showed why: 25-55% of the draft slot's rank link to `ppg3` runs through year-1 snaps (EDGE 0.489 -> 0.233, DT 0.420 -> 0.224, LB 0.530 -> 0.332, S 0.552 -> 0.418, CB 0.402 -> 0.224 after controlling for year-1 snaps). The draft slot is largely a measure of opportunity. This spec tests that directly: can anything known on draft day predict **how many snaps** a drafted defender plays better than the draft slot does? Production per snap (Stage 2) is not modelled here.

## Question
Per position, do the drafting team's pre-draft situation (snap volume and depth at the position last season, scheme, same-class competition) and a pre-selected college workload and grade add out-of-time rank information about 3-year snaps beyond the draft slot?

## Data (nothing new to load)
- Target: `snaps3` = SUM(`snaps`) over years 1-3 from `mart_idp_prospect_outcome`. Zero-snap years are rows in the mart (137 / 160 / 243 of 1,028 player-years in years 1 / 2 / 3), so a player who washes out has a small `snaps3`, not a missing one. **No snap floor**: this removes the selection that `ppg3` had (only 39-46% of player-years reached 300 snaps).
- Population: drafted defenders with a gsis id, classes 2017-2023, `years_observed = 3` (all 901), position group from `nfl_pff_position` (ED -> EDGE, DI -> DT, LB, S, CB; the 54 with no position, FB, G, HB and WR are excluded). 841 players: EDGE 191, DT 154, LB 157, S 137, CB 202.
- Folds: test classes 2020-2023, each trained on earlier classes only (as 15e, 15e-2, 15e-3). Pooled out-of-time per position.

## Features (all fixed here; all known on draft day; every join is an exact key, no name is read)
Block **T** (team situation), from `mart_idp_prospect_features` and `mart_team_def_scheme_week`:
1. `log_pick` — log of the overall pick.
2. `t_group_snaps_prev` — the drafting team's previous-season snaps at the player's group (existing column).
3. `t_group_players_prev` — players who shared those snaps (existing column).
4. `t_nickel_dime_share` — previous-season (draft year - 1) REG `(nickel_snaps + dime_snaps) / (base + nickel + dime + other_pers snaps)` for the drafting team, summed over weeks, from the `source = 'ftn_participation'` rows only (the `pff` rows hold NULL personnel columns). Join on the team code in `draft_team`; a team with no row is NULL plus an indicator.
5. `rookie_comp` — the count of defenders in `mart_idp_prospect_features` that the same team drafted in the same draft at the same position group with a **smaller** pick number (computed in the script from `draft_team`, `draft_season`, `draft_pick`, `nfl_pff_position`).

Block **C** (college workload and grade, descriptive only, not in the primary model): `c_grade_defense` and `c_snaps_defense / c_games`, from the existing `c_*` columns of the player's college season (as in 15e-2 P2). Missing -> training median plus an indicator.

## Models (ridge on standardised features; alpha chosen by leave-one-class-out inside the training classes over {3, 10, 30, 100}; missing -> training median plus an indicator; target `sqrt(snaps3)` to tame skew, ranks unaffected)
- **B0** = draft slot only (rank by earlier pick).
- **PRIMARY-S** = block T (features 1-5, plus the missing-team indicator for feature 4).
- **P-C** = `log_pick` + block C (descriptive).
- **P-TC** = block T + block C (descriptive).

## Primary test and ship rule
Per position: Spearman(PRIMARY-S) - Spearman(B0) against `snaps3` on pooled out-of-time players; paired bootstrap, 2,000 draws, seed 15, two-sided p; Holm across the five positions. A position "ships Stage 1" only if the point estimate is > 0 AND the Holm-adjusted p < 0.05. Otherwise it fails for that position; nothing is tuned and nothing is re-run.

## Reported descriptively (not gates, not a second chance)
- P-C and P-TC lifts with intervals.
- Whether a better snaps ranking carries to production: Spearman of the predicted snaps against `points3` (sum of points, no floor) and against `ppg3`, for PRIMARY-S and B0.
- AUC of "played at least 900 snaps in 3 years" (about 300 a year) and of the existing top-12 / top-24 flags, scoring each player by predicted snaps versus by earlier pick.
- Standardised coefficients and their signs per position.
- Coverage of each feature in the test classes.

## Risks stated now
1. **Power.** Test samples are about 80-115 players per position (more than 15e-3 because there is no snap floor). Only a lift of roughly 0.10-0.15 is detectable; "not significant" means no lift of that size.
2. **What the feature set cannot see.** Free-agent and trade moves after the draft, depth-chart competition from veterans by name, injuries and coaching changes are not in the data. If PRIMARY-S fails, the likely reason is that draft-day team context is a weak proxy for these, not that opportunity is unpredictable.
3. **Draft slot may already hold it.** Teams choose a slot partly from the same team need. A flat lift would mean the slot already prices team situation.
4. **Stage 2 is not decided here.** A pass would justify a separate spec for points per snap given a role (using `mart_idp_expected_*`). A fail at every position closes the "playing time from draft-day information" route.

## Not in this spec
Production per snap (Stage 2); the forward year-N to year-N+1 model; the 2016 class; CFBD play-level data; any post-draft information (veteran depth charts, training-camp news).

## Work, if approved
1. Commit this spec unchanged. 2. `ops/phase15e4_backtest.py` (read-only, reads the existing marts, no migration, no loader), committed before it is run. 3. One run, seed 15. 4. Result, descriptive tables and decisions in `REBUILD_LOG.md`; the 550-test suite unchanged. No data load, no DB write, no rebuild needed.
