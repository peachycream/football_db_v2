# Phase 15 kickoff — play-caller loader (samhoppen/NFL_public `all_playcallers.csv`)

> Scoped 2026-11-13 from a read-only look at the source repo and a comparison against the nflverse schedule (the same file `core_schedule` loads), done in a cloud session. That session had **no `fdb` database**, so nothing below was verified against your live `core_schedule`; §2.1 re-runs the comparison there. Run LOCALLY on Windows. To restart in a new session, paste everything below the line.

---

You are starting **Phase 15 (play-caller loader)** of `football_db_v2`. Read `CLAUDE.md`, `REBUILD_DESIGN.md` and `REBUILD_LOG.md` first; they are the contract. Do not re-derive earlier phases. Model the loader on `fdb/loaders/csvbase.py` (`WeekCsvLoader`) and `fdb/loaders/nflverse_rosters_weekly.py`.

## 0. The ask (settled; do not re-ask)
Load offensive and defensive play-caller by team-game, so the marts can show who is calling plays for a team in a given week (and how that changed). Context only: no player ids, no stats.

## 1. The source (already probed; do not redo the survey)
- Repo `https://github.com/samhoppen/NFL_public`, file `data/all_playcallers.csv`. Raw URL: `https://raw.githubusercontent.com/samhoppen/NFL_public/main/data/all_playcallers.csv` (~1 MB, one file, all seasons).
- Columns (verbatim, keep them): `season, week, team, game_id, off_play_caller, def_play_caller, head_coach`. One row per `(game_id, team)`. 15,096 rows, 1999–2026, no nulls, no duplicate keys.
- `game_id` is the nflverse format (`2025_01_DAL_PHI`). `week` is the nflverse schedule week, **including playoff weeks 19-22** (the file has no game-type column; `season_type` comes from `core_schedule`).
- Comparison against nflverse `games.csv.gz`, 2016 onward (6,066 team-game rows): 5,985 join exactly on `game_id` + `team`; `week` and `season` agree on every joined row; all playoff games covered; every fixture id in `tests/fixtures/games_2025_2026.csv` is in the file.
- **The 81 non-joining rows are all relocated franchises, 2016-2019.** `game_id` is identical, but the schedule keeps `OAK`/`SD` while this file writes `LV`/`LAC` throughout. `team_aliases` already maps `OAK→LV` (to 2019) and `SD→LAC` (to 2016), and `LV`/`LAC` are canonical teams. **Join on `game_id`, and compare teams through `team_aliases`; never on raw `team` strings.**
- **2026 contains rows for unplayed games** (all 18 weeks, 544 rows; only weeks 1-9 were played as of 2026-11-11). Those callers are carry-forwards/placeholders, not facts. Scope must come from `completed_weeks()`; a loader never chooses its own weeks (rule 5).
- `head_coach` agrees with `core_schedule.home_coach/away_coach` on 99.25% of rows. The misses are interim head coaches the schedule does not record (NYJ 2024 wk 6-10: file says Jeff Ulbrich, schedule says Robert Saleh; NO 2024 wk 10: Darren Rizzi vs Dennis Allen) plus one spelling difference (`Jerry Rosburg` vs `Jay Rosburg`, DEN 2022 wk 17-18).
- **No license file, README is one line, and nothing says how the file is generated or updated.** See gate 1. Source repo HEAD when probed: `613b7984070bf6c6dc0f2051e477f05f4f3911c4` (2026-11-10).

## 2. Build (in this order; stop at each gate)

### 2.1 Probe against YOUR DB first (one pass, no writes)
- Fetch the file to a scratch path. Re-run the join against **`core_schedule` in your DB**, not nflverse: coverage per season and `season_type`, the 81-row alias gap, week agreement, and the 2026 unplayed rows. Report anything that differs from §1.
- Record the real header to `contracts/samhoppen.playcallers.fields` (a missing field must fail the load).
- Decide, and say so in the gate report: is `head_coach` stored? **Yes, verbatim** (rule 3: source names are kept in `core_*`). The mart decides which head coach to expose (§2.4).

### 2.2 Table and loader
- Table `core_playcallers`, owner `samhoppen.playcallers` in `registry/sources.toml`. Next schema number is **046** (`schema/046_core_playcallers.sql`; 032 is an existing gap, do not fill it).
- Columns: the 7 source columns verbatim, plus the framework columns `season_type` and `load_id`. Primary key `(game_id, team)`. Keep the file's `week` as the source's own value; it equals `core_schedule.week` (checked).
- Loader subclass of `WeekCsvLoader`, grain `week`, `per_season_file = False` (one `all` partition), so `raw_is_final` is false and the file is re-fetched every run (it is a current-state feed, not a season-final file; a past row can be corrected).
- Override `row_key()` to look the row up by `game_id` in `self.games` (already loaded from `core_schedule` in `prepare()`) and return that game's `(season, season_type, week)`. **A `game_id` the schedule does not have is a hard failure, not a skip.** This also drops preseason structurally (rule 5); there is none in the file, and a test asserts it.
- Scope: only complete weeks from `completed_weeks()`; unplayed 2026 rows must never reach the table. Seasons `2016-` to match `core_schedule`; do not load 1999-2015 (no schedule to join).
- Raw bytes stored as received under `data/raw/`; `fdb rebuild` replays from them with zero network calls (rule 9). Record the source commit in the raw sidecar meta if cheaply available (`GET https://api.github.com/repos/samhoppen/NFL_public/commits?path=data/all_playcallers.csv&per_page=1`); the content hash is the fallback. Never print or commit `.env` values.
- Delete-scope-then-insert in one transaction; no `INSERT OR REPLACE` (rule 6).

### 2.3 Checks (rule 8: exit 0 is not proof)
Before write: required fields present. After write, per scope, roll back on failure:
- Teams in the loaded week equal the teams the schedule has playing that week, through `team_aliases` (the `WeekCsvLoader.checks` default, `team_coverage = "exact"`). Named exceptions only, with a reason, for the COVID and Hamlin weeks (copy `ROSTER_NO_GAME` / `CANCELLED_REG` logic; do not loosen a tolerance).
- Exactly two rows per game (home and away), and each row's `team` is one of that game's two teams (alias-resolved).
- `week` and `season` equal the schedule's for the `game_id`.
- No null or blank `off_play_caller` / `def_play_caller` / `head_coach`.
- Plausibility: a team has at most N distinct off play-callers in a season (pick N from the data, state it); flag a play-caller whose name appears under two different teams in the **same** week.
- Idempotent re-run (`fdb check`): second run changes zero rows.

### 2.4 Mart
`mart_playcallers` (schema 047): one row per `(season, season_type, week, team)`, source names renamed once here (rule 3), joined to `core_schedule` by `game_id`. Expose `off_play_caller`, `def_play_caller`, and **both** head coaches: `head_coach` from `core_schedule` (nflverse) and `head_coach_playcallers` from this file, plus a flag where they differ. Add `off_caller_changed` (differs from the team's previous completed game), computed at read time. No rates, no averages (rule 4). Apps read `mart_*` only (rule 10); do **not** build a page this phase.

### 2.5 `fdb weekly` (rule 11)
`weekly = true` in `registry/sources.toml`, register the loader in `fdb/loaders/__init__.py`, and run `fdb weekly` once. Add tests in `tests/test_playcallers.py`: row_key by `game_id`; the OAK/SD alias case; an unplayed 2026 week is not loaded; unknown `game_id` fails; the two-rows-per-game check; idempotency.

## 3. Gate (write to `REBUILD_LOG.md`, once)
1. **License and provenance.** The repo has no license. Before any data is committed to `data/raw/` or used in a deploy, **ask Turon** whether he has the author's permission or is comfortable with a personal-use read, and record the answer. If the answer is no, stop; nothing loads. (Say whether `data/raw/` is committed or gitignored under your existing policy.)
2. Probe (§2.1) matches §1, or every difference is explained.
3. Contract recorded; loader idempotent; in `fdb weekly`; a weekly run OK.
4. **Spot check:** for 10 team-weeks across eras (include NYJ 2024 wk 6, NO 2024 wk 10, a relocated-franchise week 2016-2019, and one 2026 week), the table equals the source file and the head-coach disagreements are exactly the ones in §1.
5. **Play-caller accuracy is NOT verified by this phase** (no second source in the repo). Say so in the log; do not imply the names are audited.
6. `fdb rebuild` x2 -> identical hash, 0 network calls. Snapshot the DB first and check for a running rebuild (`database\fdb.rebuild.db`). Tests pass on Windows.

## 4. Rules that bite here
**No name matching** (the join is by `game_id`; a play-caller name is a value, never a key); one owner per table (head coach already lives in `core_schedule`; this file's copy is a second source and so a second table); source names verbatim in `core_*`; `season_type` on every row, preseason never; scope from `completed_weeks()`; never `INSERT OR REPLACE`; non-final never served from cache; DB rebuildable from `data/raw/` + code; apps read `mart_*` only; v1 is read-only oracle, never a source. Production is `cmd.exe`: no `&&`; Python is `"C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"`.

**Stop at each gate and say plainly it is a clean stopping point.**
