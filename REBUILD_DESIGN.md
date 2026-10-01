# REBUILD_DESIGN.md — football_db v2

**Status:** DESIGN, 2026-09-26. No code written yet. This is the spec and handoff contract for the rebuild; a cold session should be able to start Phase 0 from this file alone.

**Scope decided by Turon (2026-09-26):**
- **v1 apps:** Matchups, Player Dashboard, Team Offense environment, Team Defense environment, Ownership/Rosters.
- **History:** 2016 → present.
- **CFB/devy:** a later phase. Nothing in v1 may assume it, but the identity model must leave room for it (§3.4).

**Why rebuild at all.** The v1 database did not fail because of bad data sources. It failed because of five structural habits, and every multi-day repair in `CLAUDE.md` traces back to one of them. The rebuild is worth doing only if it removes these habits **by construction**, not by remembering them:

| # | v1 habit | Cost in v1 | v2 structural answer |
|---|---|---|---|
| 1 | Player identity resolved **by name at load time** and stored as fact | slug sweep (6,248 rows), 5,233 mis-stamped `gsis_id`, McGovern ×2, Richardson, `palmer_josh` shadow | §3: one identity table keyed on `gsis_id`; loaders never resolve names; unresolved rows are kept with their source id |
| 2 | **Several writers per fact** | CSV-vs-API `pff_offense_blocking`, `draft_year` "repaired" from a table with no linemen, `draft_pick` holding two meanings | §4: source-ownership registry, one owner per canonical table |
| 3 | **Renaming source fields during ingest** | hard rules 11, 12, 13a (`pressure_rate` held sack %, `epa_total` held fantasy points, `snaps_offense` copied from another loader) | §5.2: canonical source tables keep the source's own wire names; renaming happens once, in documented views |
| 4 | **Implicit scope:** season type, week completeness and cache freshness were not stored | preseason in five tables, partial weeks frozen by cache (hard rule 14), a half-played week made permanent by clean-replace | §5.3–5.4: `season_type` on every row, schedule-driven completeness gate, raw fetches carry their own finality |
| 5 | **A gitignored DB shared across branches**, never rebuilt from code | stranded app tables, scheduled jobs vanished on checkout | §2: the DB is a **build artifact**, rebuilt from raw files by one command |

---

## 1. Principles (the rules the code enforces)

1. **The database is disposable; raw files are not.** Everything in `football.db` can be regenerated from `data/raw/` plus code. If a table can't be rebuilt, it is a bug.
2. **One owner per fact.** Every canonical table has exactly one loader. A second source can be loaded into its *own* table for cross-checking; it never writes into the owner's table.
3. **Identity is a lookup, never a judgment.** A loader copies the source's player id. Mapping to `gsis_id` happens in one place (§3), through exact keys only.
4. **Keep the source's names.** A canonical source table uses the source's field names verbatim (snake-cased). No `twp_rate`-becomes-`bad_throw_rate`.
5. **Store counts; calculate rates at read time.** Rates are only stored if the source provides them *and* they are kept in the source table under the source's name, never averaged.
6. **Scope is data, not assumption.** `season_type` is a column. A week is loaded only when the schedule says it is complete.
7. **Every loader proves itself.** Expected-field check before write, plausibility check after, idempotency check on re-run. Exit 0 is not proof (hard rule 13).
8. **Apps read marts, not source tables.** Blueprints query `mart_*` views only, so a source change doesn't ripple into five apps.

---

## 2. Architecture

### 2.1 Where it lives
**Recommendation: a new repository, `football_db_v2`.** A clean history and no inherited branches is half the point. v1 stays running, read-only, through the 2026 season for lineups, and remains the **reference oracle** for parity checks (§8). It is never a *source*: nothing is copied from v1 tables into v2.

### 2.2 Layers

```
data/raw/<source>/<endpoint>/<season>/<week|season>/<fetched_at>.{json,parquet}   immutable, git-ignored
        │   + raw_fetch_log (manifest: url/params, fetched_at, row_count, sha256, is_final)
        ▼
core_*   canonical, typed, one owner each, source wire names, season_type on every row
        ▼
id layer players / player_ids  (§3)  — applied by JOIN, never baked into core_*
        ▼
mart_*   views (or rebuilt tables where needed for speed): renamed, joined, rates computed
        ▼
app/     Flask blueprints + React pages read mart_* only
```

- **SQLite stays.** Scale is small, and the Flask apps already use it. (DuckDB is faster for PBP aggregation; it could be used in the builder for the environment marts only, writing results into SQLite. Not needed in Phase 0.)
- **Schema lives in git** as numbered SQL files (`schema/001_identity.sql`, …). `python -m fdb rebuild` = create empty DB → apply schema → replay every loader from `data/raw/` → build marts → run checks. A rebuild must need **zero** API calls.
- **A single CLI**, `python -m fdb <command>`, replaces 400+ loose `diag_/patch_/build_` scripts. Loaders are modules, not scripts. For example: `fdb fetch pff.defense_weekly --season 2026 --week 3`, `fdb load …`, `fdb check …`, `fdb weekly`.

### 2.3 Keys every fact row carries

| column | meaning |
|---|---|
| `season`, `week`, `season_type` | `season_type ∈ {REG, POST}`; PRE is never loaded (no v1 app wants it) |
| `game_id` | nflverse `game_id` where the grain is a game; null at season grain |
| `team` | normalised team abbreviation (one `teams` table maps each source's spelling) |
| `<source>_player_id` | the source's own id, **NOT NULL**, part of the PK |
| `load_id` | FK to `load_log` (which raw files built this row) |

**`gsis_id` is not stored on source rows.** It is joined through `player_ids` in the mart layer. That one choice removes the entire class of "row says player X, gsis says human Y" defects from v1 (the `patch_olx_25` family), because there is no second copy to disagree.

---

## 3. Identity

### 3.1 Tables
```sql
players(
  gsis_id TEXT PRIMARY KEY,           -- the only person key
  display_name, first_name, last_name, birth_date, position, position_group,
  draft_year, draft_round, draft_pick_overall,   -- from ONE source (nflverse), definitions fixed
  rookie_season, college, height, weight
)
player_ids(
  source TEXT, source_id TEXT,        -- ('pff','10778'), ('mfl','15234'), ('sleeper','9493'), ('pfr','...'), ('ftn','...')
  gsis_id TEXT NOT NULL REFERENCES players,
  method TEXT,                        -- 'source_native' | 'id_map' | 'jersey_bridge' | 'manual'
  evidence TEXT, added_at,
  PRIMARY KEY (source, source_id)     -- one source id → one human, enforced
)
identity_overrides.csv                -- checked into git: source, source_id, gsis_id, reason, who, date
identity_quarantine                   -- source ids that failed a check; reported, never guessed
```

### 3.2 Where mappings come from (strongest first)
1. **source_native:** the source itself carries `gsis_id` (nflverse everything, Sleeper `players`, FTN on most skill/defensive ids).
2. **id_map:** `ff_playerids` (DynastyProcess) for `mfl_id`/`pff_id`/`sleeper_id` → `gsis_id`. Known limitation: it is a *fantasy* map, with almost no offensive linemen (v1: 60 OL in 12,470 rows).
3. **jersey_bridge — DEMOTED 2026-09-26:** Phase 1 found nflverse `players.csv` carries `pff_id` natively for 98.7% of OL (0 shared ids), so this is now a fallback built only if Phase 4 resolution falls below 95%. Original rationale: `(season, team, jersey_number)` from PFF → nflverse rosters → `gsis_id`. It owes nothing to the name, so a name comparison against it is a genuine **negative** check (surname + first initial must agree). This is how v1 closed the OL gap. It is needed here from day one, because Team Offense's O-line grade depends on linemen.
4. **manual:** `identity_overrides.csv` only. Every row carries a reason.

**Never:** name-only matches, "the only candidate with that name", or fuzzy matching. A name may reject a candidate; it may never select one.

### 3.3 Invariants checked on every build
- `(source, source_id)` unique (the primary key enforces it).
- No `gsis_id` claimed by two ids **from the same source in the same season** unless it is on an allow-list (PFF NFL/NCAA ids legitimately differ).
- The resolution rate per `(table, season, position_group)` is published as `mart_resolution`. It is reported, not a gate, *except* where an app needs the rows (Phase 4 sets explicit floors).

### 3.4 Room for CFB later
College ids (CFBD, PFF-NCAA) go into `player_ids` under their own `source` values. A college-only player needs a person key before a `gsis_id` exists, so `players` will gain a surrogate `person_id` in the CFB phase, with `gsis_id` becoming a unique nullable attribute. **Do not build that in v1**, but don't hardcode "`gsis_id` is the only key" into mart SQL. Always join through `player_ids`.

---

## 4. Source-ownership registry (v1 scope)

Checked in as `registry/sources.yaml` and enforced by the loader framework: a loader may only write the tables it is registered to own.

| Canonical table | Owner / endpoint | Grain | Seasons | Feeds |
|---|---|---|---|---|
| `core_schedule` | nflverse `load_schedules` | game | 2016– | completeness gate, every mart |
| `core_rosters_weekly` | nflverse `load_rosters_weekly` | player-week | 2016– | identity, jersey bridge |
| `core_player_stats` | nflverse `load_player_stats` (weekly, REG+POST) | player-week | 2016– | Matchups (offense), Dashboard |
| `core_snap_counts` | nflverse `load_snap_counts` (PFR) | player-game | 2016– | Dashboard, env denominators |
| `core_pbp` | nflverse `load_pbp` (selected columns) | play | 2016– | Team Offense/Defense env |
| `core_participation` | **nflverse `load_participation` 2016–2025; FTN participation 2026–** | play | 2016– | personnel/formation in both envs |
| `core_ngs_*` | nflverse NGS | player-week | 2016– | Dashboard |
| `core_ff_opportunity` | nflverse `load_ff_opportunity` | player-week | 2016– | Dashboard |
| `core_pff_defense_week` | PFF `defense/summary` `week=N` | player-week | 2016– | Matchups IDP, Team Defense, Dashboard |
| `core_pff_fg_week` | PFF `field_goal/summary` | player-week | 2016– | Matchups PK |
| `core_pff_passing_week` | PFF `passing/summary` | player-week | 2016– | Team Offense (pressure), Dashboard |
| `core_pff_rushing_week` | PFF `rushing/summary` | player-week | 2016– | Team Defense (run D), Dashboard |
| `core_pff_receiving_week` | PFF `receiving/summary` | player-week | 2016– | Dashboard (routes, YPRR) |
| `core_pff_blocking_week` | PFF `offense/blocking` | player-week | 2016– | Team Offense O-line grade |
| `core_pff_coverage_scheme_week` | PFF `defense/coverage_scheme` | player-week | 2016– | Team Defense man/zone |
| `core_pff_grades_season` | PFF `offense/summary` + `defense/summary` with **`week=1,…,18,28,29,30,32`** | player-season | 2016– | Team Defense grades |
| `core_ftn_dvoa_team_week` | FTN Fantasy StatsHub `dvoa/team` (website login; **not** the FTN Data API), one week per call (Phase 10) | team-week | 2018– (REG) | `mart_team_dvoa_week` → Team Offense / Defense (not yet wired) |
| `core_fantasy_leagues`, `_franchises`, `_scoring_rules` | MFL API / Sleeper API | league-season | 2026 (+2025) | Matchups scoring, Ownership |
| `core_fantasy_rosters` | MFL `rosters` / Sleeper `rosters`, **snapshot rows with `snapshot_at`** | roster slot | current | Ownership |
| `core_fantasy_scores` | MFL `playerScores` (reported) | player-week-league | 2025– | IDP calibration truth |
| `core_idp_expected_week` | **v2's own model** (§6.1), built from `core_pbp` + `core_pff_defense_week`; no external CSV | player-week | 2016– | Dashboard IDP tiles |
| `app_wishlist`, `app_wishlist_priority` | **the app** (user-entered) | — | — | Ownership |

Notes that are decisions, not details:
- **Participation is the one planned two-source seam.** nflverse stops at 2025 ("Season must be between 2016 and 2025"), and only FTN has 2026. The row carries `source`. **Phase 5 must run a seam test on the 2021–2025 overlap** (personnel distribution per team-season within a tolerance) before accepting the seam. It must also handle FTN's 2021 `TE` vs 2022+ `Y-TE`/`H-TE` vocabulary change, which v1 hit silently.
- **PFF is always weekly** except for grades. Season totals are **summed from weekly rows** (counts only), so preseason can never get in: the week vocabulary has no preseason weeks. Grades are the exception because PFF grades are not additive, which is why that one table uses the `week=<list>` server-side aggregate.
- **User-entered app state** (wishlist, tiers, `my_entry_id`) is the only data that isn't rebuildable from raw. It lives in `app_*` tables, and `fdb rebuild` **exports and re-imports it**. It is also dumped to a checked-in `app_state/*.csv` so it survives a rebuild. `gameday_config.json`'s "who am I in each league" becomes `config/my_franchises.yaml` in git.
- **Not in v1:** FTN full charting (`/coverage/`), projections, Trinity, route studies, CFB, draft tools, PFF season summary tables. Each is its own later phase with its own owner row here.

---

## 5. Loader contract

Every loader is a module that implements the same five steps. The framework runs them; a loader can't skip one.

### 5.1 `fetch` → raw
- Writes the response exactly as received to `data/raw/…`, plus a `raw_fetch_log` row (params, `fetched_at`, `sha256`, `row_count`).
- `is_final` is set **by the framework, not the loader**: true only if the period described is closed (week: every game final and at least 24 h settled; season: past the Super Bowl). **A non-final raw file is never served from cache** (hard rule 14, all three cases: open period, empty payload including nested-empty, current-state feeds by age).

### 5.2 `validate_source`
- Compares the payload's field names with the loader's **expected field list**, which is recorded from a live response the first time and checked into git.
- A **missing** field fails the load. A **new** field warns. This is the check that would have caught `snap_counts_offense` not existing in the API, and the wrong mappings in `pipeline_nflfastr`.

### 5.3 `load` → core
- Scope is exactly one `(table, season, week)` or `(table, season)`, taken from `completed_weeks()` (derived from `core_schedule`). **A loader never picks its own scope.** Every week it loads must be listed there. The "a declared `weeks` parameter that the body ignores" defect (hard rule 13b) is impossible, because the framework does the scoping.
- Delete-scope then insert, in one transaction. Never `INSERT OR REPLACE` (hard rule 13c).
- Column values are copied under the source's names. The only transforms allowed are type casts and team normalisation.

### 5.4 `check` (post-write, runs inside the transaction; failure rolls back)
- Row count within tolerance of the same week last season.
- Plausibility bounds per column, declared in the loader (for example snap max 40–100, pass attempts per team-game 15–70).
- Games present equals games final for that week (catches the "2 teams in a week" case).
- Where a cross-source partner exists, reconciliation within tolerance (PFF snaps vs nflverse snaps; PFF PAT attempts vs TDs).

### 5.5 `idempotency`
- CI and `fdb check --idempotent` reload the last scope from raw and assert an identical content hash. A re-run that changes rows is a failure.

**Backups.** Because the DB is rebuildable, the heavy per-patch `sqlite3.backup()` routine goes away for loaders. One snapshot is still taken before any `fdb rebuild` or schema migration, and `app_*` state is always exported first.

---

## 6. Marts for the v1 apps

Every mart is a view or a rebuild-from-core table, never hand-edited. Each one documents its denominator.

| Mart | Built from | App |
|---|---|---|
| `mart_player_week` | `core_player_stats` + `core_snap_counts` + `player_ids` | Dashboard, Matchups |
| `mart_idp_week` | `core_pff_defense_week` (position from `position` field: DI→DT, ED→DE) + opponent from `core_schedule` | Matchups IDP, Dashboard |
| `mart_team_pos_allowed_week` | the two above + `core_pff_fg_week`; **raw stat sums only**, scoring at read time | Matchups |
| `mart_team_off_env_week` | `core_pbp` + `core_participation` + `core_pff_passing_week` + `core_pff_blocking_week` | Team Offense |
| `mart_team_def_env_week` | `core_pbp` + `core_participation` + `core_pff_defense_week` + `core_pff_rushing_week` | Team Defense |
| `mart_team_def_scheme_week` | `core_pff_coverage_scheme_week` (+ FTN coverage later), one row per source, the other family NULL | Team Defense |
| `mart_team_def_grades_season` | `core_pff_grades_season`, snap-weighted | Team Defense |
| `mart_roster_ownership` | `core_fantasy_rosters` (latest snapshot) + `player_ids` + `my_franchises.yaml` | Ownership |
| `mart_qb_pass_zones`, `mart_qb_dropback` | `core_pbp` (`passer_player_id` is a `gsis_id`, so no mapping is needed) | Dashboard QB panel |
| `mart_rb_run_lanes` | `core_pbp` + `core_pff_rushing_week` | Dashboard RB panel |
| `mart_idp_alignment` | `core_pff_defense_week` alignment snap columns | Dashboard IDP panel, slot/box snap rate tiles |
| `mart_idp_fp_split` | `mart_idp_week` × league scoring (tackle-family vs big-play share) | Dashboard "% Non-Tackle FP" |
| `mart_dashboard_tiles` | the marts above + `core_ff_opportunity` (Expected FP) + `core_pff_*` grades | Dashboard tiles |
| `mart_resolution` | every core table × `player_ids` | ops |

Every Dashboard mart takes `season_type` as a filter. v1's QB-zone and RB-lane panels were REG-only while other tiles were REG+POST; v2 keeps REG as the default everywhere and makes the scope explicit.

### 6.1 Expected tackles and sacks: build, don't import
v1's `idp_expected_tackles`/`idp_expected_sacks` came from an external CSV export ("IDP Show") that carries **names only**. It was resolved by name (`ingest_idp_expected_tackles_v3.py` needed position-aware name matching to stop split slugs collapsing), it is season-grain, and **there is no 2026 feed**. That is the v1 anti-pattern in one table, and an exact join to it is impossible.

v2 builds its own model instead, keyed on `gsis_id` from the start:
- **Expected tackles:** per defender-week, expected tackles = the sum over plays they were on the field for of P(tackle | role/alignment, play type, ball-carrier gap/depth), fitted on 2016–2024 and validated on 2025. Inputs: `core_pbp` (tackle attribution, `run_gap`, `pass_location`), `core_participation` (who was on the field), and PFF alignment snaps.
- **Expected sacks:** per edge/interior rusher, from pass-rush snaps × pass-rush win rate × the league sack-per-win rate, which v1 showed is the stickiest pass-rush signal (win rate YoY r 0.69 vs sacks 0.56).
- **Gate:** expected vs actual Spearman ≥ 0.80 at season grain on 2025 held out, plus rank agreement with the v1 external values on a sample (as a sanity check, not as ground truth).
- If the gate fails, those four tiles ship blank with a "model pending" label; they never fall back to the name-matched CSV.

**Carry over from v1 as settled rules (do not re-derive):**
- **Scoring is catch-all** (`diag_proj_14`). A narrow per-position MFL rule is not an override.
- **IDP calibration** is an empirical per-position factor from `core_fantasy_scores`, applied at read time (OI-8 mechanism still unexplained).
- **PK gets its default points** only when a league scores no kicking event. `side='st'`.
- MFL `FC` means fumble recovery. nflverse `fumbles` is *rushing* fumbles only, so use `fumbles_lost`.
- Multi-conference MFL leagues store one roster copy per pool.
- Season defaults are derived per app from the one mart it renders (`season_ctx` pattern).
- The colour system (`theme.css`/`theme.js`/`theme.py`) is copied over as is.

---

## 7. Weekly job — built in Phase 0, grown every phase

- `fdb weekly` = compute the last complete week → fetch → validate → load → check → rebuild marts → write `PIPELINE_STATUS.json` → Discord alert to `OPS_DISCORD_WEBHOOK`.
- **Every loader joins the weekly job in the same phase it is written.** v1 built loaders for months and never an orchestrator; Team Offense is still missing from its weekly job.
- A killed or partial run must be *visible*: status starts as `running` and the next run alerts if it finds a stale `running`. (v1's 09-22 job was killed with no trace.)
- Windows Task Scheduler: **Wednesday** 05:00, `StartWhenAvailable=True`, and the job runs the **3.13 interpreter by full path**. (Was Tuesday; changed 2026-09-30 by Turon: a week is final 28 h after its last kickoff, so Monday night settles ~Wed 00:15 ET and a Tuesday run always loaded the week before.)

---

## 8. Phases

One phase per session. Each ends with a gate written to `REBUILD_LOG.md` and a **stop point**.

| Phase | Deliverable | Gate |
|---|---|---|
| **0 — Skeleton** | new repo; `fdb` CLI; loader framework (§5) with raw store, fetch log, finality, completeness gate; `core_schedule` 2016–2026; `teams`; empty weekly job + status + alert; `fdb rebuild` works on an almost-empty DB | `fdb rebuild` twice → identical hash; `completed_weeks(2026)` matches the real schedule; `--test-alert` seen in Discord |
| **1 — Identity** | `players` from nflverse rosters 2016–2026; `player_ids` from nflverse, Sleeper, `ff_playerids`, PFF jersey bridge; `identity_overrides.csv` | invariants §3.3 pass; **trap fixtures pass** (§9); PFF OL resolution ≥95% 2016+ |
| **2 — nflverse core** | player stats, snap counts, pbp, participation 2016–2025, NGS, ff_opportunity; all in weekly job | parity vs v1 oracle on 2024 (per-player targets/rec/yds exact; team pass attempts exact); 2026 weeks 1–3 loaded |
| **3 — Fantasy + Ownership** | MFL/Sleeper leagues, franchises, rules, roster snapshots, reported scores; `app_*` wishlist tables + import from v1; Ownership app ported | `/ownership/` answers identical to v1 for a 50-player sample across all 6 MFL leagues; 0 dropped roster ids (or each listed) |
| **4 — PFF** | the eight PFF core tables 2016–2026, weekly-scoped | REG+POST proven by reconciliation: PFF defensive snaps vs nflverse snaps within 1% per team-season; O-line ≥ 30 graded per team-season |
| **5 — FTN participation 2026 + seam** | `core_participation` FTN rows 2026 (and 2021–2025 staged for the seam test only) | personnel seam test passes; TE vocabulary handled |
| **6 — Env + Matchups marts & apps** | §6 marts; Matchups, Team Offense, Team Defense ported to read marts | rankings match v1 on 2024–2025 within tolerance; any difference explained, not accepted |
| **7a — Player Dashboard** | **all v1 tiles and panels** (decided 2026-09-26): QB/RB/WR/TE/DL/LB/DB tiles, QB zones, RB lanes, IDP alignment, snap trend; built on §6 marts. v1's retired-source fallbacks (FPD, `pff_receiving` composite) are **not** carried | every tile renders for 2025 and 2026; values match v1 on 2025 for tiles whose v1 source is still trusted |
| **7b — Expected tackles/sacks model** | §6.1 | §6.1 gate |
| **8 — Cutover** | v2 serves `:5000`; v1 archived read-only | one full weekly cycle on v2 with no manual fix |

API budget note: Phase 4 is about 11 seasons × ~22 weeks × 8 facets ≈ **1,900 PFF reads**, plus one-time grade calls. It is cached forever once the periods are final. Check the PFF plan's limit before Phase 4 and spread it over several sessions if needed.

---

## 9. Lessons carried forward as tests, not data

`tests/fixtures/traps.yaml` holds each hard-won case as an assertion that v2 must pass. None of it is copied data; each check runs against v2's own tables.

| Case | Assertion |
|---|---|
| Two Connor McGoverns (PFF 10778 / 41714) | map to two different `gsis_id`s, or both quarantined; never one |
| Anthony vs Antonio Richardson | no QB stats on the OT's `gsis_id` |
| Pat Surtain / Patrick Surtain II | one human, one `gsis_id` |
| Joe Thomas (T, b.1984) vs Joe Thomas (LB, b.1991) | two `gsis_id`s |
| Preseason | `core_pff_*` has no `week` outside 1–18/28–32; 2020 league snap totals equal nflverse's |
| Half-played week | loading a scope with games not final is refused |
| Nested-empty cache (`{"coverage_scheme": []}`) | treated as empty, not served |
| `pressure_rate` / `twp_rate` family | the expected-field list contains the wire names; no column renamed in core |
| FTN 2021 `TE` | 2021 11-personnel share between 25% and 45% |
| `fumbles` | the scoring mart reads `fumbles_lost`, never `fumbles` |
| MFL catch-all scoring | 30590 LB median predicted/reported within 0.95–1.05 |

---

## 10. Decisions

**Settled 2026-09-26 (Turon):**
1. **New repository, `football_db_v2`.** This file moves there as its first commit.
2. **Player Dashboard: all tiles and panels.** This pulls the expected-tackles/sacks model (§6.1) and the QB-zone/RB-lane/IDP-alignment marts into v1 scope, as Phase 7a/7b.
3. **Sleeper:** rosters in Phase 3 for Ownership; Sleeper scoring deferred.

**Still open:**
4. **PFF read budget** for the 2016–2025 backfill (§8 note). Needed before Phase 4.

**Next action:** see `REBUILD_LOG.md`. (Phase 3 note: `my_franchises` is `config/my_franchises.toml`, TOML like the registry.)
