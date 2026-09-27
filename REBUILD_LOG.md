# REBUILD_LOG.md — football_db_v2 handoff log

One section per phase. A cold session should be able to resume from the latest section alone.

---

## Phase 0 — Skeleton — GATE PASSED 2026-09-26

**Built** (stdlib only; no pandas/nflreadpy needed yet — the schedule is a plain CSV release asset):

| Piece | Where | Notes |
|---|---|---|
| CLI | `python -m fdb {fetch,load,update,weeks,check,rebuild,weekly,hash}` | `load`/`update` are dry-run unless `--apply` |
| Raw store | `fdb/raw.py` | `data/raw/<source>/<endpoint>/<partition>/<stamp>.<ext>` + `.meta.json` sidecar. **Sidecars are the durable manifest**; `raw_fetch_log` is rebuilt from them. Files never overwritten |
| Cache rule | `raw.cache_usable` | reuse only if `is_final` AND non-empty; `is_effectively_empty` recurses |
| Loader framework | `fdb/loader.py` | 5-step contract; framework picks scopes, checks ownership, delete-scope+insert in one txn, rolls back on any check failure; `_cast` refuses to truncate `1.5` into INTEGER |
| Completeness gate | `fdb/schedule.py` | game final = result present AND kickoff + 4h + 24h passed; week complete = every game final; season closed = SB exists and final |
| Registry | `registry/sources.toml` | **TOML, not YAML** (deviation from spec §4: `tomllib` is stdlib, PyYAML is not) |
| Schema | `schema/001_meta.sql`, `002_teams.sql`, `003_core_schedule.sql` | `teams` (32) + `team_aliases` (OAK/SD/STL/LAR/LVR/JAC/WSH/ARZ/BLT/CLV/HST) |
| Schedule loader | `fdb/loaders/nflverse_schedules.py` | release asset `schedules/games.csv`; current-state feed, never final, always re-fetched (~2 MB) |
| Weekly job | `fdb/weekly.py`, `weekly.bat` | status `running` written first; stale `running` (>6h) reported; concurrent run exits 2 |
| Alerting | `fdb/alert.py` | unset → loud; non-https → refuses; failure → exception only, token never printed (verified) |
| Rebuild | `fdb/rebuild.py` | network disabled; builds to a side file, swaps only if every load passed; `app_*` exported/imported via `app_state/`; keeps 3 `pre_rebuild_*.db` |
| Tests | `tests/` (unittest, stdlib) | 23 tests: `python -m unittest discover -s tests -t .` |

**Gate results (container run, real nflverse data):**
- ✅ `fdb rebuild` ×2 → identical hash `e5ca05ae…f9079`, **0 network calls**.
- ✅ `completed_weeks(2026)` = REG 1, REG 2 — correct as of Sat 2026-09-26 (week 3: 1 of 16 played). 2025 = closed, REG 1–18 + POST 19–22.
- ✅ Non-final raw is re-fetched; final raw served from cache; empty raw never final (unit tests).
- ✅ `{"x": []}`, `{"coverage_scheme": []}` treated as empty (unit test).
- ✅ Idempotency: reloading 2026 from raw leaves the hash unchanged.
- ✅ A dropped game fails the check and the season's previous rows survive (rollback test).
- ⏳ **`--test-alert` seen in Discord — DEFERRED by Turon 2026-09-26.** All three failure paths verified. Until the webhook exists, every weekly run prints "NOBODY IS TOLD" and results live only in `PIPELINE_STATUS.json`. **Open item — carry it forward in every phase's log until closed.**

**Found on the first real load — a check that failed on reality:** 2022 had **271** REG games, not 272. BUF @ CIN (week 17) was declared no-contest after Damar Hamlin's cardiac arrest. Recorded as a named exception (`CANCELLED_REG`) — **a check that fails on real data gets a named exception, never a looser tolerance.**

**Loaded:** `core_schedule` 2016–2026 = 3,033 games.

**Facts for later phases:**
- nflverse numbers playoff weeks **19–22** (2021+) and 18–21 before; **PFF uses 28/29/30/32**. The week vocabulary must be mapped explicitly when PFF arrives (Phase 4) — never assume.
- `gametime` is US Eastern. Converted with an explicit DST rule because Windows Python has no tz database without `tzdata`.
- Team values are stored verbatim in core; `team_aliases` resolves them, and a value with no alias fails the load.

**On Windows (Turon), once** (step 1–2 deferred):
1. Create a Discord webhook in a PRIVATE ops channel; add `OPS_DISCORD_WEBHOOK=<url>` to `.env`.
2. `"C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe" -m fdb weekly --test-alert` → confirm the message arrives.
3. `... -m fdb update nflverse.schedules --apply` then `... -m fdb rebuild` then `... -m unittest discover -s tests -t .`
4. Task Scheduler: `weekly.bat`, Tuesday 05:00, StartWhenAvailable = True.

**NEXT (as written at Phase 0 close): Phase 1 — Identity** (spec §3, §8): `players` from nflverse rosters 2016–2026; `player_ids` from nflverse, Sleeper, `ff_playerids`, PFF jersey bridge; `identity_overrides.csv`; trap fixtures in §9. Phase 1 will need `pandas`/`pyarrow` if the roster assets are parquet-only — check for a CSV asset first.

---

## Phase 1 — Identity — GATE PASSED 2026-09-26

**Sources reachable from the cloud container:** nflverse release assets, DynastyProcess (raw.githubusercontent.com).
**Blocked by the container's egress policy:** Sleeper, MFL, PFF, FTN APIs. Their loaders get their first live run on Windows (Sleeper/MFL in Phase 3, PFF in 4, FTN in 5).

**Built:**
| Piece | Where |
|---|---|
| `core_nflverse_players` (players.csv, 24,830) | `fdb/loaders/nflverse_players.py` — snapshot grain, never final |
| `core_rosters_weekly` 2016–2026 (474,319 rows) | `fdb/loaders/nflverse_rosters_weekly.py` — season grain; closed seasons final |
| `core_dp_playerids` (12,508) | `fdb/loaders/dp_playerids.py` |
| `players` 26,515 / `player_ids` 154,168 / `identity_quarantine` 122 | `fdb/identity.py` (builder, one transaction, rolls back on any failure) |
| Negative name check | `fdb/names.py` — can reject a mapping, never select one |
| Tripwires | `fdb/traps.py` — 19 id traps + 3 player-fact traps, run inside every identity build |
| Overrides | `identity_overrides.csv` — reason required; empty today |
| Builders framework | `registry/sources.toml` `kind = "builder"`; run after loaders in `rebuild` and `weekly` |
| Raw retention | newest 3 non-final files per partition kept; final files never deleted |

**THE DECISIVE FINDING — nflverse `players.csv` carries `pff_id`/`pfr_id`/`espn_id`/`otc_id` natively, with ZERO ids shared across two people.** `pff_id` covers **98.7% of OL** active since 2016 (98–99% every group). v1's founding identity problem, linemen with no crosswalk, does not exist in v2. **The jersey bridge (spec §3.2 step 3) is demoted to a fallback**, to be built only if Phase 4 measures PFF resolution below the floor.

**Precedence (strongest first; a weaker source can add, never override; disagreement is quarantined):**
1. nflverse `players.csv`, 2. nflverse weekly rosters, 3. DynastyProcess (MFL ids + Sleeper fills only, name-checked), 4. overrides.
Plus: **one id per source per human** — enforced in `claim()` for every source, not just checked afterwards.

**Source errors found and handled (each is now a trap or a test):**
- **nflverse's own 2016 weekly roster** gives Damaris Johnson the pff/pfr ids of Dennis Johnson; `players.csv` has it right → why players.csv outranks rosters.
- Weekly rosters **flip Tyler Conklin's pff id** between 47124 and 47327 across seasons; `players.csv` says 47124.
- **DynastyProcess name-derived errors:** Kevin Smith's gsis on MFL "Fred Williams", DE Bobby McCray's on punter Jake Schum, Mana Silva's on "Duke Williams", 10 gsis_ids on two MFL ids. All quarantined.
- **DynastyProcess writes `NA` for blank.** Treated as NULL at cast; before that it made 51 fake pff disagreements.

**Two rules added on evidence:**
- **Hyphenated surnames:** one part of the surname counts as agreement ("Nickell Robey" = Robey-Coleman).
- **Nickname rule:** surname agrees + **exact birth date** match overrides a first-initial mismatch (Drew/Andrew Ogletree, CJ/Basil Okoye, Zeke/Ezekiel Turner, Bump/Ryan Cooper Jr. — each also matched position and team). Fred Williams-type errors still fail on surname.

**Checks that failed on reality, fixed by named exceptions (never looser rules):**
- My first roster check (32 teams every week) was **wrong**: bye teams have no roster. Replaced by *roster teams == teams the schedule has playing*, which is stricter.
- That caught **2020 COVID postponements** (wk4 PIT/TEN, wk5 DEN/NE) and **2022 wk17 BUF/CIN** → `ROSTER_NO_GAME`.
- Roster rows per team-week run 55–122 (IR, practice squad) → bound 40–130, which catches truncation/duplication, not roster rules.

**Gate results:**
- ✅ Invariants: one source id → one human (PK); one id per source per human (pff, pfr, mfl, sleeper, espn): 0 violations.
- ✅ All 22 traps pass on real data (McGovern ×2, Richardson, Surtain ×2, Joe Thomas ×2, Josh Jones ×2, Gore Sr/Jr, Michael Carter ×2, Damaris Johnson, Conklin, three DynastyProcess errors, Matthews draft year/overall pick, Antonio Richardson position).
- ⚠ **PFF OL coverage:** 98.7% of `players.csv` OL (the spec's ≥95% floor), but **565/628 = 90%** when roster-only players (1,685 new signings/practice squad not yet in players.csv) are counted. The real measure is resolution of OL **who appear in PFF data**, taken in Phase 4. Jersey bridge only if that is below 95%.
- ✅ `fdb rebuild` ×2 on real data → identical hash `f27420bd…8f7f`, 0 network calls, ~28 s.
- ✅ Idempotency on all four loaders. ✅ `fdb weekly`: 5/5 steps OK.
- ✅ 36 unit tests (offline fixtures in `tests/fixtures/*_traps.csv`), including: a McGovern pff swap in the source fails a trap and rolls back; a 25-row players file is refused as truncated.

**Coverage, players active 2025+ (MFL / Sleeper):** QB 130/129 of 139 · RB 233/230 of 265 · WR 381/376 of 480 · TE 193/190 of 249 · DL 415/384 of 543 · LB 401/380 of 475 · DB 542/485 of 704 · OL 0 (MFL/Sleeper don't list linemen). The gaps are mostly fringe/practice-squad players. **Phase 3's real test is 0 dropped roster ids**; the Sleeper players API (which carries gsis natively) will fill Sleeper gaps there.

**Quarantine on current players (2024+):** 3 MFL ids (LJ Scott, Nico Evans, Micah Simon) whose claimed gsis doesn't exist in nflverse at all — nothing correct to map to. Everything else is historical.

**OPEN ITEMS:** (1) Discord webhook + `--test-alert` (deferred by Turon). (2) Sleeper/MFL/PFF/FTN loaders need a first live run on Windows (container egress).

**NEXT (as written at Phase 1 close): Phase 2 — nflverse core** (spec §8): player stats, snap counts, pbp, participation 2016–2025, NGS, ff_opportunity; all in the weekly job; parity vs the v1 oracle on 2024. Check asset formats first — `load_pbp`/`player_stats` may be parquet-only, which would bring in `pyarrow` (first non-stdlib dependency; decide deliberately).

---

## Phase 2 — nflverse core — GATE PASSED 2026-09-26

**Still stdlib-only.** Every asset exists as CSV (pbp as `.csv.gz`; gzip is stdlib), so **no `pyarrow`**. Asset names were probed directly (the GitHub API is blocked from the container).

**Loaded 2016–2026 (weeks 1–2 of 2026):**
| Table | Rows | Loader | Notes |
|---|---|---|---|
| `core_player_stats` | 184,480 | `nflverse.player_stats` | `stats_player_week_<s>.csv`; `player_id` is gsis |
| `core_snap_counts` | 256,101 | `nflverse.snap_counts` | PFR; `pfr_player_id` → gsis via `player_ids` |
| `core_pbp` | 489,743 | `nflverse.pbp` | **117 of ~372 columns** (list = `contracts/nflverse.pbp.fields`), incl. every tackle/sack/QB-hit/PD attribution id for Phase 7b |
| `core_participation` | 449,813 | `nflverse.participation` | **2016–2025 only** (`season_range`); 2026 → FTN in Phase 5. Name/jersey lists not stored |
| `core_ngs_passing/receiving/rushing` | 5,592 / 13,623 / 5,618 | `nflverse.ngs_*` | one all-seasons file each; **week 0 (season total) not loaded** |
| `core_ff_opportunity` | 58,987 | `ffverse.ff_opportunity` | `ep_weekly_<s>.csv` from ffverse/ffopportunity |

**Framework additions:** `WeekCsvLoader` base (schedule-mapped scopes + a team-coverage check that every scheduled team is present, which is what catches a partial week in the source); `season_range`; `prepare()` hook; parse memo (one season file serves ~22 week scopes); `keep_fields` pruning while reading (a full pbp season as dicts is >1 GB); gzip; duplicate keys and type errors become **load failures naming the column**, not crashes; contract = required fields, table = union across eras (participation gained six columns after 2016).

**THREE WEEK VOCABULARIES — mapped explicitly, never assumed equal:**
- schedule / stats / pbp / snaps / ffverse: POST 18–21 (≤2020), 19–22 (2021+)
- **NGS: Super Bowl one week later** (22 / 23 — skips Pro Bowl week). NGS tables keep NGS's `week` verbatim plus a framework `schedule_week`.
- PFF (Phase 4): 28/29/30/32.

**Source facts found (each handled deliberately):**
- `fg_blocked_list` holds `"53;46"`; type inference from two sample seasons missed it because neither had a multi-block game. All `*_list` columns are TEXT. The first run **crashed** on it, so cast errors are now load failures naming the column.
- **Participation "orphans"** (1.6% of 2016 rows, not in pbp) are **empty shells** (no players either side, `n_offense` 0, no possession team): non-play events like the two-minute warning. Skipped by rule; the orphan check stays strict at 1%.
- **ff_opportunity `player_id = NA`** rows are an **unattributed team bucket, one per team-game** (419 in 2024). Kept; excluded from player resolution; checked ≤1 per team-game because **SQLite lets NULL through a PRIMARY KEY**.

**Checks that were wrong about football, corrected (all recorded in code comments):**
- CHI 2017 wk7 threw **7 passes** (Trubisky 4/7) → per-team bounds loose (3–80), league-week average tight (25–45).
- KC 2024 wk18 rested starters (max snaps 34), LV 2025 wk7 35 → per-team max ≥20; **the v1-bug signature is a LEAGUE-WEEK max of 37**, so the league-week max must be 55–110.
- Super Bowl LII averages 46.5 attempts per team → the league average applies to full weeks (≥20 teams) only.
- A participation/pbp **count ratio** is meaningless (participation includes non-scrimmage plays) → replaced by two-directional coverage: participation ⊆ pbp (≤1% orphans) and pbp passes/runs covered ≥95%.

**Gate — v1 parity replaced by cross-source reconciliation (`fdb reconcile`).** The v1 database is on Windows, not in the container. Reconciliation is the stronger test anyway: two independent paths to the same number. **44/44 pass for 2016, 2020, 2024, 2026:**
- player_stats vs pbp, per player-game: **targets 100.0%, receptions 100.0%, carries 100.0% exact**; receiving yards 98%+ (pbp `yards_gained` differs from credited yards on laterals/fumbles).
- NGS pass attempts vs player_stats: 99.6–100% exact. ff_opportunity receptions vs player_stats: **100.0%**.
- Team offense snaps (PFR) vs pbp plays within 10%: 99.6–100%.
- Resolution: pbp passer/rusher/receiver/tackler ids **100.00%**; player_stats 99.88%; snap_counts (via pfr) 99.8–99.97%; NGS 100%; ff_opportunity 100% of attributed rows.
- **`reconcile` now runs on the live season inside `fdb weekly`**, so a source that starts disagreeing raises an alert.

**Also:** ✅ offline rebuild ×2 identical (`4241f7ee…8d54`), 0 network, ~3 min · ✅ all 12 loaders idempotent · ✅ weekly 14/14 in 35 s · ✅ 44 unit tests. DB 864 MB, raw 810 MB (participation CSVs are ~50 MB/season).

**Optional on Windows:** a v1-vs-v2 parity spot check (e.g. 2024 targets per player) is now cheap, but the reconciliation above already establishes correctness independently.

**OPEN ITEMS:** (1) Discord webhook (deferred). (2) Sleeper/MFL/PFF/FTN need a first live run on Windows.

**NEXT: Phase 3 — Fantasy + Ownership** (spec §8): MFL/Sleeper leagues, franchises, scoring rules, roster snapshots, reported scores; `app_*` wishlist tables + import from v1; port `/ownership/`. **Both APIs are blocked from the cloud container**, so Phase 3 must be run on Windows (or the environment's network policy widened — see the environment docs). Code can be written here against recorded sample payloads, but its gate (parity with v1 `/ownership/`, 0 dropped roster ids) needs the live APIs and the v1 DB.

**2026-09-27:** Phase 3 handed to a LOCAL Windows session. MFL/Sleeper are still blocked from the cloud container, and the gate needs the v1 DB. Kickoff prompt: `PHASE3_PROMPT.md`. It also covers the first Windows run of the Phase 0–2 tests.

---

## Phase 3 — Fantasy + Ownership — GATE PASSED 2026-09-27 (Windows, local)

**Where things are on this machine:** v2 = `C:\Users\k-ble\Desktop\Documents\GitHub\football_db_v2` (already a clone; no second clone made). **v1 oracle = `C:\Users\k-ble\Desktop\football_db`** (not `C:\Users\k-ble\football_db` as the kickoff prompt said), opened `mode=ro` only. `.env` holds only `MFL_USERNAME`/`MFL_PASSWORD` (gitignored; `git status` clean of it). `OPS_DISCORD_WEBHOOK` NOT copied: v1's `.env` has one, but whether it is the private ops channel is Turon's call.

### Windows first run (step 0)
- **44/44 Phase 0–2 tests: 1 failure on Windows**, fixed: `rebuild` swapped the DB with `os.replace`, which Windows refuses while any process holds the file open (WinError 5). Now `_swap_in` copies the side build in with SQLite's backup API (atomic, open readers survive — the Flask app can stay up during a rebuild).
- Encoding: stdlib `open()` defaults to cp1252 on Windows; every new reader opens bytes or `encoding="utf-8"` (a Sleeper payload broke a probe that didn't). No timezone surprises.
- Backfill 2016–2026 (`fdb weekly` only loads the current season, so the other seasons were `fdb update <loader> --apply`), then **`fdb reconcile --season 2024 2026`: all ok**.

### Built
| Piece | Where |
|---|---|
| League dimension | `Scope.league` / `Scope.snapshot`; grains `league`, `league_week`, `league_snapshot` (`fdb/loader.py`). Scopes = `config/my_franchises.toml` × schedule seasons × completed weeks — never the loader. Phase 0–2 grains unchanged |
| Config | `config/my_franchises.toml` (TOML, like the registry; spec said yaml). 6 MFL + 2 Sleeper; MFL seasons 2025–2026, Sleeper 2026 (ids roll yearly) |
| MFL client | `fdb/mfl.py`: POST login (password never in a URL), cookie auth, per-(league, year) host discovery, 1.1 s spacing, 429 backoff 5/15/45/135 s then a **5-min fail-fast cooldown**, error payloads raise (never stored), `as_list` for the one-element quirk |
| Loaders (12) | `fdb/loaders/mfl.py`, `fdb/loaders/sleeper.py`; one `TYPE=league` fetch feeds 4 tables (`fetches = False` siblings read the same raw) |
| Tables | `core_mfl_{league,franchises,divisions,conferences,rosters,rules,player_scores,players}`, `core_sleeper_{league,users,rosters,players}` (`schema/007`) |
| Marts | `mart_roster_ownership`, `mart_roster_unresolved`, `mart_player_search`, `mart_wishlist(_priority)` (`schema/008`, `009`) |
| Builder | `fantasy.config` → `my_franchises`; fails if my franchise is missing or **if the mart's slot count ≠ the latest snapshot's** (a join can't drop a slot silently) |
| App | `app/` Flask: `/ownership/` search, suggest typeahead, FA browse, wishlist, reverse; JSON APIs. Reads `mart_*` only; writes `app_*` only. `theme.css`/`theme.js`/`theme.py` copied byte-identical (sha256 checked). Run: `python -m app` → :5001 |
| User state | `app_wishlist`, `app_wishlist_priority` (gsis-keyed); `fdb/wishlist_import.py` |
| Gate tool | `fdb parity-ownership --v1 <db> --explain` (`fdb/parity.py`) |
| Tests | 66 (22 new in `tests/test_fantasy.py`), all offline |

**Retention decision (roster snapshots):** raw policy `daily` = newest file per UTC day, every day kept (~1.5 MB/day for 8 leagues at most; ~80 MB/yr at the weekly cadence). Each retained raw file is its own `league_snapshot` scope, so history survives a delete-scope reload; `sync_snapshots` deletes core rows of pruned files so the table always equals a rebuild. Other current-state feeds keep 3.

### Live source facts (each verified; several contradict the carried-over list)
1. **APIKEY = the cookie is WRONG.** Sending the MFL_USER_ID token as `APIKEY` makes `TYPE=league` fail ("API Key Validation Failed"). Cookie only.
2. **Pools are MFL's own settings, not config:** `playerLimitUnit` (CONFERENCE 30590; DIVISION 57653/60398/55757/60856; LEAGUE 46276) + `rostersPerPlayer` (55757 = 2). v1's hand-kept `fa_pool_scope` agrees. **Proven on every roster load:** no player has more owners in a pool than `rostersPerPlayer` (passes all 6).
3. **Multi-conference rosters are NOT duplicated.** 30590 = 32 franchises × ~70 players = 2,230 rows; a player appears once per conference. "Elevated counts" were just big rosters.
4. **MFL ids 0800–0999 are league-scoped custom (devy) players:** the same id is a different person (or "Placeholder, Devy") in each league. Keyed `mfl:<league>:<id>`; never mapped globally.
5. **MFL reorders JSON keys and repeated elements on every call.** Rules are keyed on the rule itself (positions, event, range, points — unique in all 6 leagues), not payload position; nested JSON kept for later phases is canonicalised.
6. **`playerScores&W=18` in a league with `endWeek` 17 returns WEEK 17's scores** (labelled 17). Scopes stop at each league's `endWeek`; a payload for another week is refused.
7. **Rate limits are real:** after ~70 calls MFL 429'd `playerScores` through all backoffs, even at 4 s spacing, for ~10 minutes. `playerScores` now spaces 4 s; one refused partition no longer aborts the others (fetch/update/weekly).
8. Franchise payloads carry league-mates' email/phone/address: **not stored in core** (stay in the local raw file only).
9. Sleeper: `starters`/`taxi`/`reserve` ⊆ `players` (verified; a violation fails the load, since the id would vanish). Rosters change hands (roster 10: BigEWolf → EricKiesel).

### Identity
- **Sleeper `/players/nfl` added** below nflverse, above DynastyProcess, name-checked like DP: +1,199 ids. It caught **Sleeper swapping Tyler Conklin's and Ryan Izzo's gsis_ids** (both refused; trap added).
- **Cross-id bridge** for Sleeper players with no gsis (new signings): needs ≥2 agreeing ids, or 1 + exact birth date. One bridge alone was wrong on first run (Joey Porter Sr. carries Jr.'s rotowire_id → trap added; espn/rotowire disagree for 6 old players). Resolves CJ Daniels, Matt Hibner, Jack Strand.
- No MFL bridge needed: every NFL player on an MFL roster already resolves (via DynastyProcess).
- Traps: 22 → 24. Identity: 26,515 players, 157,301 ids, 187 quarantined.

### Darnold discrepancy (re-tested, not fixed)
30590 2025 wk1 reported **20.9**. The stored 2025 rules, read catch-all, **reproduce it exactly**: 16 PC ×1 + 150 PY ×0.05 + 14 RY ×0.1 − 1 TSK = 23.9, − 3 FLO (1 lost sack fumble) = 20.9. v1's 7.60 was a v1 interpretation bug, not a rules/score disagreement. Threshold rules (`5/300`…) didn't trigger here; their meaning is still Phase 6's to pin down. Rules are identical 2025 vs 2026 in all 6 leagues.

### Gate
- ✅ **12 MFL/Sleeper loaders:** contracts recorded from live responses (`contracts/mfl.*`, `sleeper.*`); **all IDEMPOTENT** (`fdb check`); **all in `fdb weekly` → OK 27/27** (2 min).
- ✅ **0 silently dropped roster ids.** 26,363 slots in the latest snapshots (mart = core, checked by the builder). Resolved 25,419. Unresolved **944, every one listed with its reason** in `mart_roster_unresolved`: **942 devy** (329 league-scoped MFL players, no NFL identity; CFB phase) + **2 NFL** (Sleeper: DeaMonte Trayanum 13438, Kaidon Salter 13681 — Sleeper has no gsis and no bridge meets the bar; left for an override with evidence, not guessed).
- ✅ **/ownership/ vs v1, 50 players × 8 leagues = 400 answers: 301 identical; the other 99 all explained** — 176 franchise-level differences, each matched to a transaction or draft pick dated after v1's snapshot (v1 MFL snapshot 2026-08-05, Sleeper 2026-07-06): 97 free-agent adds/drops, 59 draft picks (60398's draft ran 08-01..08-19), 11 trades, 7 waivers, 1 commissioner. **0 unexplained; 0 v1-dropped slots.** Sleeper compared by roster (v1 team → roster by exact-id overlap). Devy is excluded from the sample by rule: v1 has no exact key for league-scoped ids (0 mfl ids in 0800–0999; it used name slugs). Evidence (transactions, draftResults) is in the raw store, not loaded.
- ✅ **Wishlist imported: 7/7 v1 slugs re-keyed by exact keys, 0 unmapped** (6 by mfl/sleeper ids agreeing with v1's gsis; Doneiko Slaughter by v1 gsis + exact birth date). v1's priority table was empty. Exported to `app_state/*.csv` (checked in) and **survives rebuild** (unit test + both real rebuilds).
- ✅ **`fdb rebuild` ×2 → identical `203e1294…9bb1`, 0 network calls**, ~4.5 min. ✅ **66 tests pass on Windows.**

**Loaded:** MFL 12 league-seasons, 548 franchises, 1,230 rules, 25,481 roster slots (6 snapshots), 33,767 league players; scores 2026 wks 1–2 all leagues; **2025 complete** (finished 2026-09-27: every league wk 1 to its endWeek — 30590/57653 wks 1–17, the other four 1–18; 114,504 rows). Sleeper 2 leagues, 882 slots, 12,229 players. Raw: MFL 31 MB, Sleeper 43 MB. DB 843 MB.

**OPEN ITEMS:**
1. Discord webhook (deferred; still NOBODY IS TOLD).
2. ~~Finish the 2025 MFL scores~~ — DONE 2026-09-27 in one pass (no 429s once MFL's limit had reset).
3. Trayanum / Salter: two Sleeper NFL players unresolved — an `identity_overrides.csv` row needs your evidence.
4. PFF/FTN still need a first live run (Phases 4/5).
5. Weekly makes ~40 MFL calls; if 429s persist on Tuesday runs, spread them (e.g. `mfl.players` less often).

**NEXT: Phase 4 — PFF** (spec §8). Decision still open: PFF read budget (§10.4).

---

## Phase 4 — PFF — GATE PASSED 2026-09-27 (Windows, same session as Phase 3, by Turon's decision)

**Decisions (Turon, 2026-09-27):** read budget — "keep going until I say stop"; scope — full 2016–2026, recent seasons first; credentials — `PFF_USER`/`PFF_PASS`/`PFF_API_KEY` copied from v1's `.env` (only those lines; only `PFF_API_KEY` is used — the other two are website credentials that do not work on the API). §10.4 is closed.

### Built
| Piece | Where |
|---|---|
| Client | `fdb/pff.py`: Bearer key, throttles on `x-ratelimit-remaining` (100 reads/min), retries 429/502/503/504, **raises on `restricted_columns`** and on error payloads, `rows_of` refuses a payload that isn't exactly one row list |
| 7 weekly loaders | `fdb/loaders/pff.py` → `core_pff_{defense,fg,passing,rushing,receiving,blocking,coverage_scheme}_week`, one request per (season, week) |
| 2 season loaders | `core_pff_offense_season`, `core_pff_defense_season`: `week=<completed REG weeks>,28,29,30,32` = PFF's server-aggregated REG+POST line with grades recomputed. **Split into two tables** (spec had one `core_pff_grades_season` fed by two endpoints; one owner per table) |
| Schema | `schema/010_core_pff.sql`: every PFF field verbatim, types from live 2016 + 2025 responses (column sets identical in both eras). Framework columns `season, season_type, week` (schedule's) + `pff_week` (PFF's) |
| Checks | per week: every scheduled team present (partial week refused), defensive plays per team 30–110, contract fields; per season: `player_game_count` ≤ weeks requested (preseason leak) |
| Reconcile | `fdb/reconcile_pff.py`, run by `fdb reconcile` (and so by weekly on the live season) |
| Tests | 79 (13 new in `tests/test_pff.py`), offline |

**Week vocabulary (third one, mapped explicitly):** PFF playoffs are **28/29/30/32** (31 = Pro Bowl, empty; verified live). The schedule's POST weeks (18–21 ≤2020, 19–22 since) map onto them IN ORDER per season. 2020 has 17 REG weeks and a 14-team wild card (12 teams in wk 28) — both handled with no special case. Preseason never enters: no PFF week number reaches it.

**Finality:** a PFF week is final only when its SEASON is closed (PFF re-grades after games; v1 saw 2025 grades revised months later). The live season's weeks are re-fetched every run: ~156 reads at season's end, ~2 min. Weekly run today: 2.6 min total, 36/36.

### Found
1. **My bug, caught by the run:** partition `2025/POST19` split as `POS`+`T19` → every playoff week of the first four 2025 loaders failed. Fixed (`_split`, round-trip test); the four were re-run. No bad rows were written — the load failed loudly.
2. **PFF `upstream_timeout` (504)** on the heaviest call (2025 defense season grades, 22-week aggregation), six times running; succeeded on a later retry. Client now retries 502/504 with backoff.
3. **The `offense/blocking` report lists a player only in weeks he had block snaps** (Chase Brown 12 of 17 games), so per-player sums compare to the season line only for linemen: 98.5–100% exact (2024 misses are all off by 1 snap).
4. **nflverse/PFR gaps exposed by PFF (2026):** PFR has no week-1 row for Tariq Woolen (PHI, 70 PFF snaps) or Sebastian Joseph-Day (PIT, 18); and PFR counts one play per game that PFF does not for LV (every on-field defender +1, both weeks). The gate check attributes these by exact id instead of loosening its tolerance: PHI/PIT/LV are +0.00% once set aside, every one listed.
5. "11 defenders per snap" is NOT an invariant (12-/10-man snaps are real): 529/570 team-weeks in 2024 — reported only.

### Gate (all seasons 2016–2026: 187 checks, 0 FAIL)
- ✅ **Defensive snaps PFF vs nflverse/PFR within 1% per team-season: every closed season 2016–2025 = 32/32 teams raw** (worst: NE 2018 −0.96%, CLE 2023 −0.75%, MIA 2025 +0.73%). 2026 (2 weeks): 29/32 raw, the 3 fully explained per player-game (item 4).
- ✅ **REG+POST proven:** every PFF table holds exactly the schedule's completed weeks, PFF weeks only in 1–18/28–32; **weekly defensive snaps = PFF's own season line EXACTLY in all 11 seasons** (2024: 409,637 = v1's REG+POST truth; 2016: 394,417). If preseason leaked into either, those could not be equal.
- ✅ **O-line:** all 32 teams have graded linemen every season; **6–8 distinct graded OL minimum per team-season, 303–350 OL-seasons per year.** The spec's "≥ 30 graded per team-season" cannot be meant per team (a team dresses 7–10 linemen); recorded as measured, not asserted — Turon to confirm the intended reading.
- ✅ **PFF OL resolution: 100.00% in every closed season** (2026: 214/215, one new signing). **The jersey bridge (demoted in Phase 1) is not needed.** Defenders and receivers 100% 2016–2025.
- ✅ Pass attempts vs nflverse: within ±1 league-wide every season (2024 18,580 = 18,580).
- ✅ 9 loaders idempotent; in `fdb weekly` (36/36 OK). ✅ 79 tests pass.
- ✅ **`fdb rebuild` ×2 → identical `391600f4…da1e`, 0 network calls**, ~7.5 min each (wishlist exported and re-imported both times).

**Loaded 2016–2026:** defense 108,385 · blocking 100,617 · coverage scheme 70,870 · receiving 44,358 · rushing 22,954 · passing 6,758 · FG 5,529 player-weeks; season lines offense 11,819 / defense 11,176. ~1,800 PFF reads, no 429. Raw PFF 411 MB; DB 924 MB.

**OPEN ITEMS:** (1) Discord webhook (deferred). (2) Trayanum/Salter Sleeper overrides (Phase 3). (3) Confirm the OL gate's intended reading. (4) Weekly MFL call volume (Phase 3 item 5).

**NEXT: Phase 5 — FTN participation 2026 + seam** (spec §8).

---

## Phase 5 — FTN participation 2026 + seam — GATE PASSED 2026-09-27 (Windows, same session)

**Credentials:** `FTN_USER`/`FTN_PASS`/`FTN_API_KEY` copied from v1's `.env` (only those lines, same as PFF). Only `FTN_API_KEY` (the "Legacy" key, raw in `Authorization`, no `Bearer`) is used.

### Built
| Piece | Where |
|---|---|
| Client | `fdb/ftn.py`: paginated season feeds; the raw payload is the pages exactly as received, wrapped in one JSON array |
| Loaders (4) | `fdb/loaders/ftn.py` → `core_ftn_games` (2020–), `core_ftn_plays`, `core_ftn_participation` (2021–), `core_ftn_all22` (2026–, one call per game) |
| Seam | **`mart_participation_personnel`** (builder `participation.seam`, `fdb/participation.py`): one row per offensive pass/run play, **nflverse < 2026, FTN ≥ 2026, `source` on every row** |
| Schema | `schema/011_core_ftn.sql` (FTN names verbatim, types from live 2021/2025/2026), `012_mart_participation.sql` |
| Checks | `fdb reconcile`: overlap seasons run the seam test; 2026 runs FTN-only plausibility + all-22 id resolution |
| Tests | 85 (6 new in `tests/test_ftn.py`) |

**Deviation from spec §4, deliberate:** the spec had FTN rows written into `core_participation` with a `source` column. That is two writers on one table (rule 2) and two vocabularies under one set of names (rule 3). Instead each source keeps its own core table, and **the seam is the mart**, which carries `source` per row, exactly as §4 wanted of the row.

### Found (each is now a check, a test or a named exception)
1. **FTN `/plays` caps a page at 1,000 whatever `count` says**, so "a short page is the last" returned **1,000 plays for a whole season**, silently. Pagination now advances by rows received; the end is a page shorter than the largest page seen, or a 404 "Season not found" after a full page (`/plays` answers 404 past the end, not `[]`).
2. **FTN skill positions are ALIGNMENT, not personnel.** A tight end split wide is `WR`/`SLT`. By alignment, FTN showed 25% "10 personnel" vs nflverse's 0.5%, and every team-season failed the seam by up to 56 points. **Personnel is counted from each skill player's roster position by exact gsis id** (nflverse weekly roster that season, else `players`). The 2021 `TE` → 2022+ `Y-TE`/`H-TE` vocabulary change is therefore handled by construction; alignment codes stay verbatim in core.
3. **Three personnel vocabularies:** nflverse 2016–22 `1 RB, 1 TE, 3 WR`; nflverse 2023+ `1 C, 1 FB, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 2 WR` (FB split out, counted as a back); FTN via roster positions. A play whose 5 skill players aren't all backs/TEs/receivers (a 6th lineman reporting) is "unknown" on both sides alike, and counted.
4. **FTN files the 2024 Super Bowl (gid 6733, played 2025-02-09) in its 2025 plays feed**, not 2024's. Every other Super Bowl is in its own feed, and `/participation` files this one correctly. Rows are placed by game through `core_ftn_games`, never by feed, and `FTN_PLAYS_FEED` names this one partition.
5. **FTN typo:** 2022 wk8 SF @ LA kickoff (pid 983219) has `off='LAC'`. The plays check is now stricter than team coverage (every play's off/def must be the two teams of its own game), and that pid is a named erratum; the row itself is stored verbatim.
6. **FTN lists the 2022 wk17 BUF @ CIN no-contest** (gid 6134, 0–0). The games check reuses the schedule's `CANCELLED_REG`, the same named exception.

### Gate
- ✅ **Personnel seam test 2021–2025 passes** (tolerances fixed before looking): every team-season within 5 pts on every group (11/12/21/13/10/22/other); worst TEN 2021 11 (2.2 pts), MIA 2025 10 (4.4 pts). League within 2 pts every season, e.g. 2024 11: 63.7% nflverse / 63.8% FTN; 12: 22.8 / 22.8.
- ✅ **TE vocabulary handled** (finding 2). ⚠ **§9 trap REVISED — Turon to confirm:** the spec's "FTN 2021 11-personnel share in 25–45%" encodes v1's number, which v1 computed from alignment codes (v2's first run reproduced it: 34.3%). By roster position both sources say ~62% (nflverse 62.2, FTN 61.4). The trap's purpose, catching 2021 TEs miscounted, is kept as "FTN 2021 11-share within 2 pts of nflverse" (passes), and the old band is still reported.
- ✅ **2026 FTN:** weeks 1–2 loaded, 3,731 personnel plays; 11/12/21 shares inside FTN's own 2021–2025 range; **all-22 ids 112,046/112,046 = 100% resolve**.
- ✅ Every FTN week loads only when complete: every scheduled team present, every play's teams are its game's teams, participation covers ≥99% of scrimmage plays.
- ✅ 4 loaders idempotent, all in `fdb weekly` (41/41 OK, 5.0 min). ✅ 85 tests pass.
- ✅ **`fdb rebuild` ×2 → identical `f0622f16…fbfe`, 0 network calls**, ~10 min each (wishlist exported and re-imported both times).

**Loaded:** FTN games 1,966 (2020–2026); plays 241,072 and participation 233,075 (2021–2026; 2021–2025 staged for the seam); all-22 5,094 plays (2026). Seam mart: 329,303 nflverse + 3,731 FTN plays. Raw FTN 395 MB.

**OPEN ITEMS:** (1) Discord webhook. (2) Trayanum/Salter overrides. (3) OL gate reading (Phase 4). (4) **§9 FTN 2021 trap revision** (above). (5) **FTN play ↔ nflverse play link** (pid ↔ play_id) is not built: the seam mart is play-level per source, but joining FTN 2026 plays to `core_pbp` (EPA per personnel) needs it. Phase 6 builds it when the env marts need it, by exact keys (game + quarter + clock + down/distance/yardline).

**NEXT: Phase 6 — Env + Matchups marts & apps** (spec §8).
