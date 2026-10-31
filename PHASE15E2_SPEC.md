# PHASE15E2_SPEC.md — second IDP prospect attempt (DRAFT, awaiting Turon's approval; nothing below has been run)

**Status:** drafted 2026-10-31 after the 15e gate failed (`REBUILD_LOG.md`, Phase 15e). This file is the pre-registration: once Turon approves it, it is committed UNCHANGED before any 15e-2 number is computed. A result that fails is reported as failed. No spec edits after the first run; a different idea is a third spec.

## Question
15e's model (draft slot + 24 college stats, one ridge per position) did not beat the draft slot. Turon's objection: draft slot cannot be the whole story. 15e-2 asks, per position, whether **pre-draft information that 15e did not use, chosen by football role BEFORE looking**, adds out-of-time rank information beyond the draft slot.

## What 15e did not use (the new information)
| Block | Contents | Source | Needs |
|---|---|---|---|
| **A. Athletic** | speed score, vertical, broad jump, 3-cone, shuttle, bench (each with missing -> training median, plus `has_<test>`) | `mart_idp_prospect_features` (already there) | nothing |
| **B. Role-specific college production** | per position, below | features mart | nothing |
| **C. Trajectory** | `college_seasons`, `left_censored`, age at the final college season, and the **previous** college season's grade, snaps and key counts, and the change from the previous to the final season | features mart + NEW columns | migration `050` adds `p_*` columns for season = college_season - 1 (NULL when none), builder extended, same leakage check |
| **D. Landing spot** (knowable at the draft) | the drafting team's previous-season defensive snaps per game at the player's group, and the number of its players at that group with >= 300 snaps that season | `core_pff_defense_week` by team and PFF group, joined to `draft_picks.team` | an EXACT team-code map (draft table abbreviations -> PFF/NFL abbreviations, from `teams` / schedule). If the map is not 100% exact, Block D is dropped and said so; it is never fuzzy-matched |

Block B (fixed by role, not by 15e's profile results; DT and LB lists overlap those leads, which is disclosed and is why Block B alone is not the headline):
- EDGE: pressure rate, career pass-rush win rate, true-pass-set win rate, sacks per game, PFF pass-rush grade
- DT: stops per game, PFF run-defense grade, PFF defense grade, career pass-rush win rate, tackles per game
- LB: stops per game, tackles per game, box-snap share, PFF run-defense grade, PFF coverage grade
- S: PFF coverage grade, tackles per game, slot share, free-safety share, tackles for loss per game
- CB: PFF coverage grade, coverage yards per target, catch rate allowed, pass breakups per game, interceptions per game

## Population, label, folds (identical to 15e so the two are comparable)
Drafted defenders, classes 2017-2023 (three observed years), position from `players.pff_position` (DI->DT, ED->EDGE, LB, CB, S; others excluded and counted). Label `ppg3` = sum(points)/sum(games) over years 1-3, defined only with >= 300 defensive snaps; flags `top12_any`, `top24_any`. Rolling origin: test class N in 2020-2023, train on 2017..N-1, pooled out of time. Same bootstrap (2,000 paired draws, seed 15).

## Models (per position; nested; all fixed here)
- **B0** draft slot only (prediction = -pick).
- **P1** log pick + A. **P2** log pick + B. **P3** log pick + C. **P4** log pick + D.
- **FULL** log pick + A + B(position) + C + D (D only if its map is exact).
Ridge on standardised features; alpha chosen **inside the training classes** by leave-one-class-out CV over {3, 10, 30, 100} (never on the test class). Logistic ridge (same grid on C = 1/alpha) for the flags.

## Primary test and ship rule (one primary hypothesis per position)
Primary: Spearman(FULL) - Spearman(B0) on pooled out-of-time `ppg3`, paired bootstrap p (two-sided), **Holm-adjusted across the five positions**. A position ships only if the point estimate is > 0 AND the Holm-adjusted p < 0.05. Otherwise nothing ships for it. P1-P4 ablations, AUC/Brier for the flags and coefficient signs are reported as descriptive, never as a second chance at the gate.

## Power, stated now
Test samples are about 50-93 players per position; 15e's intervals were about ±0.15 wide. 15e-2 can only detect a lift of roughly 0.15 or more. "Not significant" will mean "no lift of that size," not "no lift."

## Diagnostic (not part of the gate)
Role vs skill: how much of the draft slot's relationship with `ppg3` runs through year-1 snaps (a post-draft quantity, so diagnostic only), reported per position.

## Not in this spec (separate decisions)
Expected tackles / expected sacks to split role from finishing in the LABEL (NFL-side models exist; needs its own spec). Loading PFF NCAA 2015 to add the 2016 class (about +15% players; needs the `FIRST_SEASON` decision). Any CFBD feature (no exact bridge).

## Work, if approved
1. Migration `050` + builder extension (previous-season columns) with the leakage check, rebuild x2, tests. 2. Team-code map check for Block D. 3. Commit this spec unchanged. 4. `ops/phase15e2_backtest.py`, one run, report whatever it says in `REBUILD_LOG.md`.
