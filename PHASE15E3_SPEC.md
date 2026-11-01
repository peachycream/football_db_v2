# PHASE15E3_SPEC.md — third IDP prospect attempt: CFBD scouting and recruiting data (DRAFT, awaiting Turon's approval; nothing below has been run)

**Status:** drafted 2026-10-31 after 15e and 15e-2 both failed their gates (`REBUILD_LOG.md`). This file is the pre-registration: once approved it is committed UNCHANGED before any 15e-3 number is computed. A failed result is reported as failed; no edits after the first run; another idea is a fourth spec.

## What changed since 15e-2
The CFBD endpoint survey (`REBUILD_LOG.md`, 2026-10-31) found that CFBD's `/draft/picks` joins the nflverse draft table EXACTLY on (draft year, overall pick) (2,312 of 2,312 picks, 2017-2025) and carries a CFBD player id, so CFBD data can now reach NFL outcomes by exact key for drafted players. A probe for this spec found what CFBD does NOT have for defenders: `/ppa/players/*` and `/stats/player/success` hold offense only (QB, RB, WR, TE), so there is no CFBD player-level advanced defensive metric.

## Question
Do two CFBD information sources that no earlier attempt used — (E) the pre-draft scouting ranks CFBD attaches to each draft pick and (F) high-school recruiting pedigree — add out-of-time rank information beyond the draft slot, per position? Kept to a handful of features per position, because 15e and 15e-2 both overfit with many.

## New data (all exact-key)
| Piece | Source | How it joins | Cost |
|---|---|---|---|
| `core_cfbd_draft_picks` (loader `cfbd.draft_picks`, season grain) | CFBD `/draft/picks?year=Y`, 2017-2026 | to `core_nflverse_draft_picks` on (season, overall pick) | 10 calls |
| `core_cfbd_recruiting_players` (loader `cfbd.recruiting_players`, season grain) | CFBD `/recruiting/players?year=Y`, recruit classes 2012-2022 | recruit `id` to `core_cfbd_roster.recruitIds` (exact; `athleteId` in the recruiting payload is empty) | 11 calls |
| `mart_idp_prospect_cfbd_bridge` (builder `idp_prospect.cfbd_bridge`) | the two tables + roster | gsis_id <-> CFBD athlete id by draft slot; recruit <-> athlete by `recruitIds`. A name or a college string may REJECT a pair, never select one: rejected = draft team contradicts the nflverse team code, or a roster row names two recruit ids (left NULL and counted) | none |
| features mart columns (migration `051`, builder extended) | the bridge | `dp_pre_rank`, `dp_pre_pos_rank`, `dp_pre_grade`, `rec_stars`, `rec_rating`, `rec_ranking`, `rec_year`, `cfbd_athlete_id`, and the CFBD season counts (TFL, sacks, QB hurries, pass deflections, tackles) of `college_season` | none |
Both loaders: `weekly = true` (the current draft year is refetched, past years come from cache), contracts recorded from the live response, scope-checks with named floors, rebuild x2 identical. About 21 CFBD calls in total (the account has 291 left today and resets 2026-11-01 00:00 UTC).

## Bridge gate (before any model)
Of the 1,148 drafted defenders 2017-2025: at least 95% get a CFBD athlete id via the draft slot (the survey measured 1,144, 99.7%) with zero team contradictions; coverage is reported per class and position. Recruit coverage (a drafted defender with a recruiting row) is REPORTED, not gated: transfers, walk-ons and JUCO players have none, and `has_recruit` carries that to the model.

## Blocks and models (per position; ridge standardised, alpha by leave-one-class-out inside the training classes over {3, 10, 30, 100}, missing -> training median plus an indicator; all fixed here)
- **E scouting:** `dp_pre_grade`, `dp_pre_pos_rank`, and the reach = draft pick minus `dp_pre_rank` (positive = taken later than the consensus rank). Indicators for missing.
- **F recruiting:** `rec_stars`, `rec_rating`, log of `rec_ranking`, `has_recruit`.
- **G CFBD college production (secondary, descriptive):** per-game TFL, sacks, QB hurries, pass deflections and tackles from CFBD for the same season as the PFF stats.
- **Models:** B0 = draft slot only. **PRIMARY = log pick + E + F** (at most 8 features). P-E, P-F, P-G = log pick + that block alone (descriptive). Same label, folds, snap floor and bootstrap as 15e and 15e-2 (classes 2017-2023, test classes 2020-2023, pooled out of time, 2,000 paired draws, seed 15).

## Primary test and ship rule
Per position: Spearman(PRIMARY) - Spearman(B0) on pooled out-of-time `ppg3`, paired bootstrap two-sided p, Holm across the five positions; a position ships only if the estimate is > 0 AND the Holm-adjusted p < 0.05. Otherwise nothing ships for it. Blocks P-E, P-F, P-G, AUC/Brier for top-12 / top-24, coefficient signs and a bootstrap interval of the lift are reported descriptively.

## Two risks stated now
1. **Provenance of the scouting ranks.** CFBD does not say when `preDraftGrade` and the rankings were set. If the primary model lifts and E drives it, the lift is NOT accepted as a result until provenance is shown (CFBD's source note, or ranks present for players drafted before the data existed); if provenance cannot be shown the result is reported as "unverified, possibly leaked".
2. **Power.** Test samples are about 50-93 players per position; only a lift of roughly 0.15 or more is detectable. "Not significant" means no lift of that size.

## Not in this spec
CFBD play-level data (`/plays`, `/plays/stats`: per-play player credits with down, distance and yard line; about 200 calls a season for 2013-2025, far over this month's quota; a possible later spec). CFBD portal and returning-production endpoints (no defender-level exact bridge for them has been tested). Any year before the 2017 class, and the predict-playing-time and role-versus-finishing ideas from 15e-2.

## Work, if approved
1. Commit this spec unchanged. 2. Loaders with contracts, tests and registry rows; load; idempotency; rebuild x2. 3. Bridge builder with the gate above and tests. 4. Migration `051` and builder extension, leakage and plausibility checks, rebuild x2, full tests. 5. `ops/phase15e3_backtest.py`, one run, result and decisions in `REBUILD_LOG.md`.
