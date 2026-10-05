# Phase 11 kickoff — Matchup of the Week card (data + render)

> **STATUS 2026-10-03: §2.1 steps 1–3 and 5 are BUILT and gated (`mfl.weekly_results`, `mfl.lineups`, history 2020+; see the Phase 11 entry in `REBUILD_LOG.md`). `mfl.projected_scores` is built too (§2.1 step 4). `mart_matchup_card` (§2.2, `schema/028`), the upcoming-week loaders (`schema/027`) and the review page `/matchup/` are BUILT. The featured-game picker (`fdb/matchup_pick.py`, `schema/029`) is BUILT too. The PNG renderer (`fdb/card_render.py`, `fdb card`, `/matchup/card.png`) is BUILT. The week-selection fix (`fdb/matchup_weeks.py`, `fdb card --mode`) is BUILT. The manual Discord post for 30590 (`fdb post`, `app_post_log`) is BUILT; one test post went out 2026-10-05 and the post was then reworked (three messages: two landscape images plus a written breakdown). Remaining: a first send to a private test channel, then deciding on scheduling. Earlier: resume at the Discord post (only on Turon's explicit say-so per run). The card has PREVIEW and FINAL (recap) states; actuals come from `core_mfl_weekly_results` + `core_mfl_lineups`, projections from the last snapshot before kickoff.** Decided by Turon: the featured game is the *picked* pairing (v1's selector), and the card shows that pairing only.

Run LOCALLY on Windows (MFL is unreachable from the cloud container). Paste everything below the line as the first message of a **new** session.

---

You are starting **Phase 11 (Matchup of the Week: data + card)** of `football_db_v2`. Read `CLAUDE.md`, `REBUILD_DESIGN.md` and `REBUILD_LOG.md` in full first; they are the contract. Phases 0–10 are done. Do not re-derive them. This phase was scoped on 2026-10-03 from the v1 bot's output; nothing below has been built.

## 0. Why this phase exists
v1's Discord "Matchup of the Week" card (Steelers vs Bengals, TINO NFL Elite, 2026 week 4, posted Mon 2026-09-29 08:00) showed: both records 0-0, scores 0.00 / 0.00, "FINAL", margin 0.00, "all-time series tied 1–1 · 2 meetings", and prose that contradicted the numbers. Turon wants the data correct and the card redesigned. The Steelers/Bengals are **fantasy franchises named after NFL teams** (MFL franchise ids in league 30590), not NFL clubs.

### Causes found by reading v1 (`C:\Users\k-ble\Desktop\football_db`, read-only; none reproduced by running it)
1. `app/scouting.py` `_records()` and `_series()` call `_matchups(..., fetch=False)` = **cache only**. A week/season that was never cached counts as nothing, silently. Records come out 0-0; the series sees only whatever seasons were cached ("2 meetings" in a league that began in 2020).
2. `mfl_weekly_results()` caches **any non-empty payload for 30 days**, including an in-progress week (no `result` W/L yet), so it freezes. This is hard rule 7 broken.
3. Wins are counted only when MFL's per-franchise `result` flag is `W`/`L`. Ties and missing flags drop out. Decide from the **scores**.
4. `scouting_weekly_job.py` defaults `week` to `war_engine._detect_current_week()` for BOTH modes. A Monday-morning *recap* therefore targeted week 4 (not yet played) instead of week 3. That is where 0.00 and FINAL came from. A recap must use the **last completed week**; a preview the next unplayed week.
5. The card never checks game state, so unplayed games render as FINAL with 0.00.
6. Records ignored that each franchise plays two games a week (verify v1's handling); prose paragraphs are generated separately from the numbers ("favors Cincinnati by 28.03" under "Margin 0.00"; "Strong DL" vs the board).

## 1. State of v2 you build on (verified 2026-10-03)
- MFL client `fdb/mfl.py` (cookie auth, 1.1 s spacing, 429 backoff, `as_list`). Loader base `fdb/loaders/mfl.py`; **`PlayerScoresLoader` (grain `league_week`, `season_types = ("REG",)`, `raw_is_final` from the schedule + settle, `last_week` from `core_mfl_league.endWeek`, `scope_rows` refuses another week's payload) is the template to copy.**
- Existing tables: `core_mfl_league`, `_franchises` (has `name`, `abbrev`, `division`, **`icon`, `logo`** — the franchise logos come from MFL, no external CDN), `_divisions`, `_conferences`, `_rules`, `_rosters` (snapshots), `_player_scores` (player-week). Registry: `registry/sources.toml`. Contracts: `contracts/mfl.*.fields`.
- **Missing**: MFL `weeklyResults` (franchise-week score and W/L, per matchup, starters/non-starters) and `projectedScores`. v2 has no matchup/results table at all.
- `config/my_franchises.toml` lists MFL seasons **2025, 2026** only. The all-time series needs the league's whole history (v1: `SERIES_START_YEAR = 2020`).
- v1's Scouting Preview/Recap Windows tasks are still **enabled** and still post from v1's DB (Phase 8 left them on by Turon's choice). Do not disable or edit them in this phase without asking.
- Design reference for the card: `docs/matchup_card_mockup.html` (static; every number is a placeholder except the position-board and player figures copied from the v1 post).

## 2. Build (in this order; stop at each gate)

### 2.1 Data
1. **Probe first, live, one league-week** (`30590`, 2025 wk1): record the real `weeklyResults` and `projectedScores` JSON shapes to `contracts/` (`mfl.weekly_results.fields`, `mfl.projected_scores.fields`). Check: are `score`/`result` present for a finished week; what a bye/unplayed week returns; is there a tie marker; the one-element-is-a-bare-object quirk; does `W` past `endWeek` return another week (it does for `playerScores`).
   **Probe DONE 2026-10-03 (live, league 30590; raw JSON was kept only in the session scratchpad, so the loader's own first fetch re-records it):**
   - **Each franchise plays TWO games a week** (32 franchises, 32 matchups/week, 64 franchise slots; e.g. 2026 wk3 franchise 0029 appears vs 0015 and vs 0016, with the same `score`). 2026 records after 3 weeks are out of 6 games (Steelers 0029 4-2, Bengals 0003 5-1). Records, series meetings and "last meeting" must count per **game (matchup)**, while points for counts a week's score **once**. A card needs a rule for which of a franchise's two games is the featured one (Turon to decide).
   - `weeklyResults` franchise keys: `id`, `score`, `result`, `isHome`, `opt_pts`, `optimal` (comma ids), `starters` and `nonstarters` (comma ids), `player` (list of `{id,status}`); an unplayed week has NO `score`/`opt_pts` and **`result` = "T" for every franchise** plus a `spread` key. So `result` is not evidence of a game: state comes from the schedule, never from `result` or a zero score.
   - `projectedScores` = per-PLAYER **per-week** projections (896–1,051 players, one blank score in 1,006). This league scores on a large scale (team weeks 650–1,170; top players 100–150 a week), so v1's player values (Gibbs 142.25, Barkley 100.57) ARE real week-4 projections: **my earlier suspicion that they were whole-roster or season values was wrong.** Gibbs' id 16162 projects exactly 142.25.
   - Starters: week-4 `starters` has 28–29 ids per franchise. Steelers' projected starter total 1,268.37 vs Bengals 1,360.19 (gap 91.8; v1's card said 28.03, unexplained: its lineup may have been empty or different at post time, to check). Whole-roster sums are 1,703/2,035, so the starter filter matters.
   - 2026 points for through wk3: Steelers 2,680.95, Bengals 2,854.35 (a week's score counted once).
   - `weeklyResults` also carries `optimal`/`opt_pts` (best lineup): a possible "points left on the bench" stat.
   The card sums projections over **starters only**, and every number is labelled projected or actual.
2. **`mfl.weekly_results` → `core_mfl_weekly_results`**, grain `league_week`, REG (check POST/playoff weeks: 30590 `endWeek` 17), one row per franchise per matchup, **source names verbatim** (`id`, `score`, `result`, `opt_pts`, `starters`, `nonstarters`… whatever the probe shows). Finality from the schedule (copy `PlayerScoresLoader.raw_is_final`); a non-final raw file is never served from cache; nested-empty counts as empty. Check: every franchise in the league appears once per week, both sides of a matchup present, scores plausible, **`result` agrees with the score comparison** (reported, tolerance for ties).
3. **History for the series.** Extend `seasons` for league 30590 to its first season (verify with MFL; v1 says 2020) in `config/my_franchises.toml`, and load weekly results for those seasons only (not every table). Closed seasons are final, cached forever. **Mind the MFL rate limit** (~70 calls then 429): ~7 seasons × 17 weeks ≈ 120 calls; spread across runs (loader already fails fast on a cooldown) and use the existing 4 s spacing for the heavy endpoint. Franchise ids can change across seasons; the series is by **franchise id as MFL gives it per season**, so check that id → owner is stable (`core_mfl_franchises.owner_name`/`username`) and document any season where it is not. **Never match by franchise name.**
4. **`mfl.projected_scores`** only if the card needs player projections that `core_mfl_player_scores` cannot give. It is current-state: never final until the week is, keep-3 policy like other current-state feeds. (v1 used it for the position board and win probability.)
5. **Weekly job (rule 11):** both loaders get `weekly = true` in the registry in this phase and the rows in `registry/sources.toml`. Every one idempotent (`fdb check`).

### 2.2 Mart: `mart_matchup_card` (`schema/027`; 026 is projected scores, 025 the weekly-results core tables, 024 Trinity)
One row per `(season, league_id, week, matchup)`; apps and the Discord job read **only** this.
- `state` ∈ `PREVIEW | LIVE | FINAL`, derived from the schedule, never from "score is 0".
- Records **through the week before** (W/L/T from the scores of weeks < week); points for/against; last-3 form; division standing; `is_division_rivalry` from `core_mfl_divisions`.
- All-time series: W-L-T, meetings, last meeting (season, week, both scores) — from final weeks only, the matchup's own week excluded.
- Position-group projected points per side (QB/RB/WR/TE/DL/LB/DB) and top-3 starters per side, joined to players **by `player_ids` (`mfl`) only**; unresolved ids listed, not guessed. Position grouping = v1's `POS_GROUP` (it is a mapping of position codes, not names).
- **Rates at read time:** win probability computed in the reader from the stored point totals, not stored (rule 4). Win probability must be consistent with the displayed margin.
- Franchise `logo`/`icon` URL and color live as columns here; NFL-team colors: **v1's `NFL_COLORS` table is a name→hex lookup on the franchise's own name** — port it to a checked-in `config/franchise_colors.toml` keyed by **franchise id per league**, with a contrast check (v1 colors are too dark/too similar for some pairs, e.g. Ravens, Bengals vs Broncos).
- Builder fails (rolls back) if: a FINAL matchup has a 0.00 score, records through the week don't equal the sum of that team's loaded weeks, or a franchise appears in two matchups in one week.

### 2.3 Render + post
- `fdb`-side renderer (HTML → PNG, same path v1 used; check what v1's `scouting.py` actually does for the image before choosing) implementing `docs/matchup_card_mockup.html`: franchise logos as large translucent watermarks (≈20% opacity) behind the names, diagonal team-color split, state pill, win-probability bar, tug-of-war position board, tale of the tape, players to watch, three templated takeaways **derived from the same numbers as the graphics**. Logos fetched once, stored under `data/` and embedded as base64 (Discord's image render can't be trusted to fetch them).
- **Do not post to Discord in this phase** unless Turon says so in chat for that run (sending a message is outward-facing). Produce PNGs in `data/` for review, from a past FINAL week and a PREVIEW week.
- Week selection fix (cause 4): recap = last completed week from `completed_weeks()`; preview = next unplayed. Both pure functions with tests.

## 3. Gate (write results to `REBUILD_LOG.md`)
- `weekly_results` (and `projected_scores` if built): contract recorded from a live response; idempotent; in `fdb weekly`; weekly run OK.
- **Records:** for every franchise in 30590, W-L through week N equals MFL's own `standings` for the same point in the season (pull standings once as an oracle for 2025; every difference explained). Not 0-0 for any team after week 1.
- **Series:** for 3 hand-picked rivalries, the meeting list matches MFL's own matchup pages/`weeklyResults` for each season, including the Steelers–Bengals pair. Report meeting count per season loaded; no season silently missing (the builder lists seasons with no rows).
- **v1 oracle:** compare v1's cached values where v1 has them; each difference is v1's cache gap, listed, not accepted silently.
- A FINAL card can't show 0.00; a PREVIEW card can't say FINAL (tests). Win probability and margin agree (test).
- Two rendered PNGs reviewed by Turon (1 FINAL, 1 PREVIEW).
- `fdb rebuild` ×2 → identical hash, 0 network calls. Tests pass on Windows.

## 4. Rules that bite here (from CLAUDE.md)
No name matching (franchises by MFL id; players by `player_ids`); one owner per table; source names verbatim in `core_*`; counts stored, rates at read time; `season_type` on every row, preseason never; never `INSERT OR REPLACE`; non-final never cached; exit 0 is not proof; DB rebuildable from `data/raw/`; apps read `mart_*` only; v1 is a read-only oracle, never a source. **Before any DB write, check for a running `fdb rebuild`** (side file `database\fdb.rebuild.db`), per the Phase 10 lesson. Production is `cmd.exe`: no `&&`.

## 5. Open questions for Turon (ask at the start; don't assume)
1. Back to which season does league 30590's history go, and were franchise ids/owners stable? (Series depends on it.)
2. Should the same card also be produced for the other MFL leagues, or 30590 only?
3. Keep v1's Scouting Preview/Recap tasks running until v2's job replaces them, then disable (recommended), or switch at the gate?
4. Preview timing (v1: Thursday 9:00) and recap timing (Tuesday 8:00 is too early: Monday night settles ~Wednesday 00:15 ET; v2's weekly runs Wednesday 05:00, so recap after it).

**Stop at the gate and report. Say plainly that it is a clean stopping point.**
