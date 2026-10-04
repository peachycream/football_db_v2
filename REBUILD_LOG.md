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

## Phase 6 — Env + Matchups marts & apps — GATE MET 2026-09-27, pending Turon's review (Windows, same session)

### Built
| Piece | Where |
|---|---|
| pbp columns | `schema/013_pbp_env_columns.sql`: `fixed_drive_result`, `drive_play_count`, `tackled_for_loss`, `fumble_forced` (contract updated; pbp reloaded from raw) |
| Loader | `nflverse.ftn_charting` → `core_nflverse_ftn_charting` (2022–; `schema/014`): play-action / screen / no-huddle / rushers, **and both play ids (nflverse + FTN)**. This closes Phase 5 open item 5: the FTN↔pbp play link is the source's own key, not a clock/down match |
| Matchups marts | `schema/015_mart_matchups.sql`: `mart_team_week_opponent`, `mart_player_allowed_week` (off from `core_player_stats`, IDP from PFF defense, PK from PFF FG), `mart_mfl_rules`, `mart_mfl_reported_week` (mfl→gsis→pff, exact ids), `mart_mfl_leagues` |
| Scoring | `fdb/scoring.py`: MFL rules at read time, per player-game; `idp_calibration` (v1's method) |
| Env marts | builder `env.build` (`fdb/env.py`) → `mart_team_off_env_week` (split grain), `mart_team_def_env_week`, `mart_team_def_scheme_week`, **sums only**; PFF season views in `schema/016_mart_env.sql`. Formulas are v1's (agent_offense_env_weekly_v1 / build_def_env_weekly) |
| Apps | `app/matchups.py` (`/api/matchups/meta|rankings|trends`), `app/env.py` (`/api/team-offense-env`, `/api/team-defense-env`, `/gameday`), **v1 JSON contracts unchanged**; `app/viz.py` serves v1's built React bundle (copied to `app/static/viz`) at `/viz/offense`, `/viz/defense`, `/viz/matchups`, `/matchups/`, injecting `window.__SEASON_CTX__` from the marts. Unported v1 pages/APIs (scatter, player, chat panels, `/gameday/live` widget) are not routed |
| Tests | 104 (19 new in `tests/test_phase6.py`) |

### Found
1. **⚠ Turon: MFL scoring rules are ADDITIVE, measured.** For a player at position P every rule naming P applies, the catch-all row and narrower rows together (30590 2025 wk1–3 exact-to-0.01: TE 175/217 additive vs 7/217 widest-only). This *refines* the settled catch-all rule: a narrow row adds, it does not override. An event with only narrow rows (RA: RB/WR/TE) never scores for a QB. Increment rules (`5/300`) truncate and are never negative. Offense exactness vs MFL-reported: 98.6–99.4% in all 6 leagues. v1's rules table (UNIQUE on league/positions/event/range) collapsed multi-row ladders, so league-mode rankings differ from v1 **by design**.
2. **Offensive players' special-teams tackles score** (TK/AS catch-all rows name QB/RB/WR/TE): offense mart rows carry nflverse `def_tackles_solo`/`def_tackle_assists`; generic PPR excludes them.
3. **2026 4-man pressure has no source:** nflverse's FTN mirror has `n_pass_rushers` but no pressure flag. It stays NULL (never 0) and the page shows "—".

### Gate — rankings vs v1 (live localhost:5000), 2024–2025, all 32 teams, every metric diffed
**Matchups (PPR, full season):** IDP DE/LB identical; DT/CB/S/PK near-identical; offense ρ 0.94–0.99. Every gap traced to measured v1 defects: name-slug duplicate player rows (374 in 2024, 268 in 2025, e.g. Chris Olave also filed as `cole_chris`), current-vs-weekly position, 517 mis-stamped v1 gsis rows (2025), 98 two-point conversions v1 lacks. Stat lines agree 18,152/18,250; collapsing v1's duplicates + weekly position cuts the max team diff from 71 to 9.7 FP/season.

**Team Offense / Team Defense league tables:** Spearman ρ ≥ 0.997 on every ranked column (EPA, PROE, pace, success; EPA allowed, success allowed, havoc, pts/drive); most columns identical rank for all 32 teams. Every difference, explained:
| Difference | Size | Cause |
|---|---|---|
| ±1 play for a few teams; single-week trend points | ≤0.005 EPA/play season | **nflverse revised pbp after v1's cache (2026-07-09)**: e.g. 2024_15_MIA_HOU 2274 (HOU fake punt) and 2025_02_SEA_PIT 3686 → `no_play`; 2025_13_JAX_TEN 933 added. MIA's one-play defensive diff is the same fake punt |
| Personnel splits | large (SF 2025 21-share: v1 0.2%, v2 37%) | **v1 bug**: 2023+ strings split out FB and v1 read only `RB`. v2 = nflverse's own `offense_personnel` string on **every** counted play (verified SF/MIN/BAL 2024–25) |
| Target share by position | up to 10 pts | **v1 duplicate rows**: TEN 2024 v1 575 targets vs pbp 510; v2's buckets sum to exactly 510. (JAX 2025: Travis Hunter's targets are `other` because nflverse lists him CB; v1's current position said WR) |
| Pass-block grade (BUF, PIT, NYJ, MIA, CHI, TEN) | up to 1.2 | **v1 name matching**: the two Connor McGoverns (NYJ pff 10778, BUF pff 41714) and Zach Frazier (PIT) are missing from v1's `pff_offense_blocking`; v2 keys on the PFF id (both McGoverns are already identity traps) |
| PFF defense grades | ≤0.28 | same class: every differing team-season has 1–2 player rows missing in v1's slug-keyed `pff_grades`, never extra |
| Scheme | 2025 | v1 has no 2025 scheme data (returns null); v2's `through_season` is 2025 |
| Week range mid-season | — | the bundle asks for weeks 1–18; v2 clamps to the last week with data (v1 echoed 1–18 and listed unplayed weeks as "personnel missing") |

- ✅ Pages verified in the browser (2026 opens by default; all three render on v2 data).
- ✅ `nflverse.ftn_charting` idempotent; `env.build` re-run → identical row hashes (72,618 / 5,586 / 11,108 rows, ~4 min).
- ✅ `fdb weekly`: every step OK including `nflverse.ftn_charting` and `env.build`.
- ✅ **`fdb rebuild` ×2 → identical `384c218e…9bbe2`, 0 network calls**, ~16 min each (wishlist exported and re-imported both times). ✅ 104 tests pass.

**OPEN ITEMS:** (1) Discord webhook. (2) Trayanum/Salter overrides. (3) OL gate reading (Phase 4). (4) §9 FTN 2021 trap revision (Phase 5). (5) Sleeper scoring deferred (§10.3), so Sleeper leagues are not offered in Matchups. (6) `env.build` is the slowest builder (~4 min, all seasons every run); scope it to changed seasons if weekly time matters. (7) v1 Game Day widget and chat panels not ported.

**NEXT: Phase 7a — Player Dashboard** (spec §8).

## Phase 7a — Player Dashboard — GATE PASSED 2026-09-28 (Windows, same session)

### Built
| Piece | Where |
|---|---|
| Builder | `dashboard.build` (`fdb/dashboard.py`) → `mart_player_week` (nflverse stats + snap counts by exact pfr id + inside-20 targets from pbp; snap-only weeks kept), `mart_qb_dropback_week`, `mart_qb_pass_zones_week`, `mart_rb_run_lanes_week` (v1's ingest filters exactly). Post-write checks: every nflverse stat line present, targets equal core per season, ≥99% snap rows resolve, zone attempts 97–100% of nflverse attempts, lanes ≥90% of designed runs |
| Views | `schema/017_mart_dashboard.sql`: `mart_pff_offense_season`, `mart_pff_defense_season` (alignment/role snaps, counts, grades, position_group DI→DT ED→DE), `mart_pff_qb_dropbacks_season`, `mart_pff_receiving_week`, `mart_pff_rushing_week`, `mart_ngs_passing_week`, `mart_ff_opportunity_week` (season_type from the game's schedule type), `mart_player_league_points_week` (MFL reported, exact mfl id → gsis), `mart_player_profile` |
| APIs | `app/dashboard.py`: all 11 v1 `/api/dashboard/*` routes, **v1 JSON contracts**; `/viz/player` serves v1's page (season context `player` from `mart_player_week`). The player key is the gsis id; v1's deep link `?player=` works with it |
| Tests | 113 (9 new in `tests/test_phase7a.py`) |

Where §6 lists `mart_idp_week`, `mart_idp_fp_split` and `mart_dashboard_tiles`: IDP player-weeks are Phase 6's `mart_player_allowed_week` (side `def`); the non-tackle split and the tiles are computed at read time from the marts (scoring is never stored, rule 4). `mart_resolution` (ops) is not built yet.

### Decisions made in the port (each changes a number vs v1, deliberately)
1. **Position is per season, from the source.** Defenders bucket by PFF's position that season; offense by nflverse's position in the player's last REG week. v1 used one current label for every season.
2. **Retired sources not carried (spec):** WR/TE target share, air-yards share and targets come from nflverse (v1: FPD); inside-20 targets from pbp (`yardline_100 ≤ 20`, pass attempt, not 2-pt) for every season. v1's FTN rule needs FTN's throwaway flag (`qbta`), which v2's FTN feed does not carry. **The FPD route tree has no successor: `/routes` returns `has_data: false`, so the page hides that panel.**
3. **QB CPOE** = NGS weekly CPOE weighted by attempts; **passer rating** = the NFL formula on REG totals (v2's loader keeps NGS weeks, not NGS's week-0 season row). Verified: Stafford 2025 weighted CPOE 2.0330 = NGS's own season row 2.03298.
4. **Expected FP and RB routes are REG / REG games.** v1 put playoff games in the numerator and divided by REG games (CMC 2025: v1 470.9 = REG 433.9 + POST 37.0 expected FP; routes 567 = 517 + 50).
5. **Expected tackles/sacks tiles (DE/DT 1,2,3,6; LB 1,2,3,6; CB/S 1,2) show "model pending (Phase 7b)"**, per §6.1. Never the name-matched vendor CSV.
6. **IDP alignment and the RB PFF chips cover 2016+** (v2 has PFF from 2016; v1 2023+). Missed-tackle rate is computed from counts: `missed / (tackles + assists + missed)`, which equals PFF's column.
7. **% Non-Tackle FP** uses v2's additive rules per player-week (Phase 6 finding); v1 used the collapsed catch-all row. Under "Default" scoring the header, tiles and split use v1's house IDP formula.
8. League list: MFL leagues as `mfl:<id>:<season>`; Sleeper leagues listed **locked** ("scoring deferred, §10.3").

### Gate
- ✅ **Every tile renders for 2025 and 2026**: all 11 endpoints for the top 6 players of every bucket, both seasons, Default and 30590 scoring: 0 errors, 0 `n/a` tiles, 9 tiles each, none slower than 3 s. Checked in the browser: QB (Allen) and CB (Surtain) 2026 pages render with their profile sections.
- ✅ **Values vs v1, 2025, top 25 per bucket, every tile.** Exact where the v1 source is still trusted: QB yards/att/TDs/rush, passer rating, PFF grade, YPA; RB touches/rush yards/carries/targets/snap share/target share/PFF grade; WR/TE receptions/yards/PFF grades/route grade/WOPR/snap share; IDP PFF grades, slot/box rate, IDP points. Every non-exact value traced:
  | Difference | Cause |
  |---|---|
  | Per-game values for Allen (16 vs 17 G), Lamb, Parkinson, Otton | a week with snaps but no stat line (Allen wk18: 1 snap). v1's own rule counts it; v1's game logs had no row. Totals identical |
  | CPOE (0/25 exact) | v1's NGS season row is stale; v2 equals NGS's current season row |
  | Expected FP, RB routes | v1 playoff numerator (decision 4) |
  | WR/TE target share, air-yards share, targets, inside-20 | FPD retired (decision 2); nflverse share within ~1 pt |
  | Cam Ward passer rating, Chig Okonkwo WOPR/snap/route grade | v1 has no row (null) |
  | Buckets (26 of 225) | per-season position (decision 1: Kyle Van Noy ED, Brandon Jones S, Scott Matlock FB in 2025), **and v1 defects**: v1's 2025 "top defenders" include retired namesakes holding current PFF lines (T.Y. Hilton as DT, Jordan Mills, Corey Washington, Dantrell Savage) |
  | IDP points | **v2 = MFL's own records by exact id**: 17,993 of 18,015 shared player-weeks equal; v1 filed 194 non-zero weeks under retired namesakes (Kris Jenkins 2001–10, Bryan Thomas, Cody Brown: 471 pts) and missed 230 (Asante Samuel 76, Brandon Jones wk15 17). 16 of 18,332 MFL rows are unresolved (league-scoped devy ids) |
  | % Non-Tackle FP | additive rules vs v1's collapsed catch-all (decision 7) |
  | Expected-tackles/sacks tiles | Phase 7b (decision 5) |
- ✅ `dashboard.build` idempotent (identical row hashes; 256k / 6.8k / 57.6k / 62k rows, ~1.5–2 min).
- ✅ `fdb weekly`: 44/44 OK, including `dashboard.build`.
- ✅ **`fdb rebuild` ×2 → identical `7b347841…bb32`, 0 network calls** (~12–16 min each; wishlist exported and re-imported both times). The second run's raw `fdb hash` printed `7af590cf…`: Phase 7b's schema file (`018`, an empty `core_pff_pass_rush_week`) was written while it ran, and the rebuild applied it. Every shared table is identical; excluding that empty table the hash is `7b347841…` again. ✅ 113 tests pass.

**OPEN ITEMS:** (1) Discord webhook. (2) Trayanum/Salter overrides. (3) OL gate reading (Phase 4). (4) §9 FTN 2021 trap revision (Phase 5). (5) Sleeper scoring deferred. (6) `env.build` + `dashboard.build` rebuild all seasons every run (~6 min together). (7) Route-tree panel has no source (FPD retired): PFF's route-level facet would be a new loader, Turon's call. (8) `mart_resolution` (ops) not built.

**NEXT: Phase 7b — Expected tackles/sacks model** (spec §6.1).

## Phase 7b — Expected tackles/sacks model (§6.1) — tackles GATE PASSED; sacks gate NOT met → tiles pending by Turon's decision 2026-09-29 (Windows, same session)

### Built
| Piece | Where |
|---|---|
| Loader | `pff.pass_rush_week` → `core_pff_pass_rush_week` (facet `defense/pass_rush`, report `pass_rush_summary`, 2016–2026; `schema/018`, `contracts/pff.pass_rush_week.fields`). Counts `pass_rush_wins` / `pass_rush_opp` (win rate = wins/opp, verified equal to PFF's). Checks: wins ≤ opp ≤ pass-rush snaps, sacks ≤ snaps, league pass-rush snaps within 1% of the defense facet's |
| Model | builder `idp_model.build` (`fdb/idp_model.py`, `schema/019`) → `mart_idp_expected_tackles_week`, `mart_idp_tackle_rates` (240 cells, inspectable), `mart_idp_expected_sacks_week`, `mart_idp_sack_rates`. Fitted on **2016–2024 only**; 2025 held out |
| Dashboard | Tackles vs Exp, Run/Pass Tkl vs Exp, Tkl vs Exp/G are live (DE/DT tile 6; LB 1,2,3,6; CB/S 1,2). v1's percentile convention (PERCENT_RANK within position + season, pool ≥100 on-field plays, prorated). The three expected-SACK tiles stay "model pending (§6.1 sack gate)" |
| Tests | 119 (6 new in `tests/test_phase7b.py`) |

**Expected tackles** = Σ over the scrimmage plays a defender was ON THE FIELD for of P(credit | PFF position group, play kind, ball-carrier gap, depth). On-field sets come from nflverse participation (2016–25) and FTN all-22 (2026, joined by nflverse's FTN mirror): gsis ids at source, no mapping. Credits use every pbp tackle slot, v1's settled convention. Cell rates are shrunk toward the parent cells (200 pseudo-plays). Role is deliberately coarse, because v1's bake-off showed a finer role model explains away the residual. **Expected sacks** = pass-rush wins × group sacks per win (DE 0.164, DT 0.122).

### Found
- **PFF pass-rush facet: 5 rows in 217 weeks break their own counts at source.** Each is a 1–2 snap DB/LB rush: 2 wins on 1 opportunity (PFF's own win rate 200.0), 1 win on 0 opportunities, or 2 sacks on 1 snap. The raw scan found the complete list; the rows are stored verbatim and named in `PASS_RUSH_ERRATA`, and the check stays strict for every other row.
- A DNS outage mid-backfill (2020 wk12 → 2016) failed the fetches cleanly; nothing partial was written, and a re-run completed them.
- **The 7a rebuild "mismatch" was not nondeterminism.** Schema 018 was written while rebuild 2 ran, so rebuild 2 carried an extra empty table. Every shared table was identical (recorded in 7a's entry).

### Gate (§6.1: expected vs actual Spearman ≥ 0.80, season grain, 2025 held out; + rank agreement with v1's vendor values as a sanity check)
| | pool | Spearman 2025 | by group | vendor agreement (expected / vs-exp) |
|---|---|---|---|---|
| **Tackles** | 702 defenders ≥100 plays | **0.949 ✅** | DT 0.897, DE 0.923, LB 0.945, CB 0.907, S 0.946; actual/expected 1.00–1.06 | 0.964 / 0.874 (n 681) |
| **Sacks** | 266 DE/DT ≥100 rush snaps | **0.713 ❌** | DE 0.758, DT 0.556 | 0.948 / 0.889 (n 252) |

**⚠ Decision for Turon: the sack gate.** No variant clears 0.80 on 2025. The same pool, each fitted on 2016–2024:
| model | 2025 | 2020–2024 (leave-one-season-out) | predicts next season's sacks (r) |
|---|---|---|---|
| wins (spec) | 0.713 | 0.76–0.85 | 0.597 |
| pressures (v1's model) | 0.790 | 0.81–0.88 | 0.603 |
| vendor IDP.Show | 0.735 | — | (v1: 0.607) |
| actual sacks themselves | — | — | 0.540 |

2025 is a hard year for sacks: the vendor's own expected sacks reach only 0.735 there. Both v2 models predict next season's sacks better than actual sacks do, which is what makes "sacks vs expected" meaningful. Options: (a) keep the three sack tiles pending (spec as written, current state); (b) switch to the pressure model and accept 0.79 on 2025 with 0.81–0.88 elsewhere; (c) restate the gate as "beats the vendor on held-out same-season agreement and beats actual sacks on next-season prediction", which both models pass.

**Decided 2026-09-29 (Turon): (a).** The three sack tiles stay "model pending", per §6.1 as written. The sack marts are still built weekly (they cost nothing extra and keep the evidence current), but no app reads them.

- ✅ `pff.pass_rush_week` idempotent; `idp_model.build` idempotent (identical row hashes, ~4.5 min).
- ✅ `fdb weekly`: 46/46 OK, including `pff.pass_rush_week` and `idp_model.build`.
- ✅ **`fdb rebuild` ×2 → identical `1aa5a11f…017b`, 0 network calls** (~22 min each; the pass-rush errata weeks reload from raw exactly). ✅ 119 tests pass.

**OPEN ITEMS:** (1) Discord webhook. (2) Trayanum/Salter overrides. (3) OL gate reading (Phase 4). (4) §9 FTN 2021 trap revision (Phase 5). (5) Sleeper scoring deferred. (6) `env.build` + `dashboard.build` + `idp_model.build` rebuild all seasons every run (~10 min together). (7) Route-tree panel has no source. (8) `mart_resolution` not built. (9) Sack tiles pending (decision (a)); revisit if a sack model clears 0.80 on a held-out season.

## Phase 8 — Cutover — IN PROGRESS: v2 is live; gate = the first unattended weekly run, Wed 2026-10-07 05:00 (Windows, 2026-09-29/30)

### Done 2026-09-29 (each change approved by Turon in chat)
| Change | Detail |
|---|---|
| **v2 serves :5000** | Task `FootballDB v2 App` (at logon) → `ops\start_app.bat` (3.13 by full path, `APP_PORT=5000`, log `data\logs\app.log`). Started via the task and verified: every page and API 200 on :5000 |
| **Hub at `/`** | v1's landing page had a hub; the React pages' "Hub" link points at `/`. `/` now lists the five ported apps, and the nav carries all five (was a redirect to `/ownership/`) |
| **v2 weekly scheduled** | Task `FootballDB v2 Weekly`: **Wednesday** 05:00 (moved from Tuesday 2026-09-30, below), StartWhenAvailable, 3 h limit, `ops\weekly.bat` → `python -m fdb weekly`, log `data\logs\weekly.log`. **Proven through the scheduler itself** (Start-ScheduledTask 06:48): exit 0, 46/46 steps OK, 11.6 min |
| **v1 archived** | Its four data-writing tasks were **disabled, not deleted**: Weekly Capture All, Matchup Refresh, Weekly NFL Capture, Weekly Env Capture (NFL and Env had been failing since 9/16, result 1). Left as they were, by Turon's choice: Scouting Preview/Recap (Discord posts from v1's DB), Media Reverify, the six past-dated digests. v1's DB file stays writable because the scouting jobs still use it. Rollback commands are in README "Operations" |
| Tests | 120 (hub test added) |

### Found
- **v1 never had an ops webhook.** `OPS_DISCORD_WEBHOOK` is present but EMPTY in v1's `.env`, so nothing was copied. Alerts stay unset until Turon creates a webhook and pastes it into v2's `.env` (then `fdb weekly --test-alert`).
- **Tuesday 05:00 was always one week behind → moved to Wednesday 05:00 (Turon, 2026-09-30; §7 updated).** A week is final 28 h after its last kickoff (GAME_HOURS 4 + SETTLE_HOURS 24, rule 7), so Monday night's game settles Wednesday ~00:15 ET. Today's scheduled-task run correctly loaded nothing new: week 3 settles 2026-09-30 00:15 ET. Moving the task to **Wednesday 05:00** would load each week the morning after it settles, with the same 28 h guard. The task was re-triggered 2026-09-30 05:50 through the scheduler to load week 3 (its first Wednesday slot had passed before the trigger existed).
- **The 2026-09-30 run failed (exit 1), and it had to: FTN all-22 lags.** Week 3 was final at 00:15 ET, but at 05:51 FTN answered 404 "Game not found" for all 16 of its games, including Thursday's (6 days old); week 2's games were there. `ftn.all22` failed the week, and `idp_model.build`'s coverage check then rolled back the whole model. Every other source loaded week 3. Left alone, **every** Wednesday run would fail the same way, so the gate could never pass without a manual fix. Fixed in the framework, not by a retry:
  - `loader.NotPublished`: raised only on the source's own explicit answer. `Loader.publish_grace_days` defaults to **0 (never pending)**; `ftn.all22` sets 14. The weekly job reports a not-published week as **PENDING** (status file + alert line `ok, PENDING - ...`) while the week is inside the grace, and as a FAIL after it, so a feed that never arrives cannot hide.
  - `ftn.all22`: NotPublished while ANY game of the week still 404s "Game not found". (First version called a partly published week a failure; the 12:50 re-run showed FTN publishes game by game, 1/16 that afternoon, the Monday game first, so partial is the same lag.) A partial week is never loaded; any other HTTP error still fails.
  - `idp_model.build`: coverage is judged per week. A week with NO on-field list at all is left out and reported pending (the 2026 expected-tackle tiles run a week or so behind the other tiles). Partial coverage still fails.
  - Verified live: `ftn.all22` rc 0, "2026/REG03: not published yet (0.3 of 14 grace days)"; `idp_model.build` no failures, "PENDING 2026 REG3". 124 tests (4 new).
- **The home connection drops for minutes at a time** (2026-09-28 and twice on 09-30: DNS `getaddrinfo failed`, `connection forcibly closed`). The re-run after the lag fix failed only on FTN fetches for that reason. `fdb/http.py`, the only network path, now retries network-level errors 4 times with backoff (15/30/60/120 s, ~4 min). HTTP error RESPONSES are never retried there (callers own 429/404), and a disabled network (rebuild) is never retried or counted. 128 tests (4 new, `tests/test_http.py`).
- **The app died unseen.** Tasks run as the user open a visible console; the app's window got closed (`^C` in `app.log`, no reboot since 9/26, only standby events), and a logon trigger does not restart a process that dies mid-session. Now both tasks run **headless** (`conhost.exe --headless cmd.exe /c ...bat`: no window to close), and `start_app.bat` **restarts the app 10 s after it exits**, logging each exit (verified: killed pid 48920, back as 56100 in 10 s). To stop the app on purpose, disable the task.
- **End-to-end after all fixes (2026-09-30 13:08, through the scheduler): `OK (46 steps)`, exit 0.** The only notes are `ftn.all22: ok, PENDING` (week 3: 1/16 games published) and `idp_model.build: ok, PENDING`. `fdb rebuild` ×2 → identical `fde5dde4…97c7`, 0 network calls (the pending week reads "1 with no raw file"). Week 3 is live on :5000 (Team Offense weeks 1–3; Matchups opens on week 4). 129 tests.
- **Daily MFL rosters (Turon, 2026-09-30):** task `FootballDB v2 Rosters` runs daily at 06:00 (headless, StartWhenAvailable, 30 min limit): `ops\daily_rosters.bat` → `fdb update mfl.rosters --apply`, log `data\logs\rosters.log`. Each run is a new snapshot per league; raw keeps the newest per day, and core rows of pruned snapshots are removed, so `/ownership/` always reads the latest. First run through the scheduler: exit 0, all 6 leagues; 46276 changed that day (947 → 935 rostered).
- **Frontend source moved into v2 (`frontend/`), and the QB zone chart's LOS fixed.** Turon: "the LOS is off". In v1's `QbPassingProfile.tsx` the label column was 56 px, so the right-anchored "Behind LOS" (~53 px) started at x=−3 and the SVG edge clipped it, and "LOS" sat above the line inside the 0–9 row. Now the column is 76 px and "LOS" is centred on the line (measured live: "Behind LOS" starts 17 px inside the SVG; the "LOS" label's y equals the line's). Before any change, the copied source was proven to reproduce the served bundle (`vite build`: identical but for the order of Vite's preload list); after the fix only `PlayerDashboard` changed (+39 bytes). `node_modules` is a junction to v1's packages: nothing downloaded, nothing in v1 edited.
- **Sleeper rosters added to the daily job (Turon, 2026-10-01).** `ops\daily_rosters.bat` now runs `fdb update mfl.rosters` then `fdb update sleeper.rosters`; exit is non-zero if either fails (the log line names both codes). Scheduler test: `exit=0 (mfl=0 sleeper=0)`, both Sleeper leagues fetched.
- **Route tree restored from FTN (Turon: "route tree data is missing").** v1's tree read FPD's per-route file (retired); Phase 7a left it empty. FTN participation charts each skill player's route on every play from 2026 (13 route types; its 2021–2025 route columns are empty). New `mart_player_routes_week` (`schema/020`, built by `dashboard.build`): routes, targets, catches and yards per player-week-route, on plays FTN types PASS or RUSH (a route run on a play that became a scramble counts; no-plays don't). Checked against PFF routes for 147 receivers: median 0.964, p10–p90 0.92–1.02 (PASS-only was 0.909). Targets, catches and yards were checked against nflverse (targets exact for 334 of 346, all within 1; receptions exact; yards within 2 for 343), and the builder now fails if a week's route-tree targets drift >2% from nflverse. `/api/dashboard/routes` returns v1's shape: mix %, TPRR, YPRR per spoke; FPD's proprietary win rate, separation and ADOR are null (the page omits them). Seasons before 2026 answer `has_data: false` and the panel hides. Verified on :5000: Smith-Njigba 2026, 90 routes (PFF 93), 36 targets, 3 weeks. 131 tests.
- **Targets-by-route history, 2016–2025 (Turon, 2026-10-01).** Before FTN there is no routes-run data, only the route of the TARGETED receiver (nflverse participation `route`, NGS). New `mart_player_targets_by_route_week` (`schema/021`, `dashboard.build`): targets, catches and yards per player-week-route; route-tagged targets are 98.6–99.9% of nflverse targets every season (checked on every build, 97–100.5% or it fails). The vocabulary changes in 2023 (2016–22: FLAT/CROSS/HITCH/IN/OUT/ANGLE…; 2023+: QUICK OUT/DEEP OUT/IN/DIG/SHALLOW CROSS/DRAG…) and does not map across, so each season shows its own route names, short → deep. `/routes` sends `basis: "targets"` when a season has no FTN routes, and the wheel (frontend `RouteTree.tsx`) then reads "Targets by route", sizes spokes by target share, colours them by yards per target and fades below 8 targets. Verified on :5000: Smith-Njigba 2025, 161 targets / 17 weeks; Davante Adams 2019, 127 targets on the 12-type vocabulary. 132 tests.

### Gate (spec: one full weekly cycle on v2 with no manual fix)
- ⏳ Pending the first unattended scheduled run: **Wed 2026-10-07 05:00** (loads week 4). The check: `data\logs\weekly.log` shows exit=0 and 46/46 ok, the new week is loaded in core and marts, and pages on :5000 show it, with no manual step.

**OPEN ITEMS:** (1) Discord webhook (create, then paste). (3) Trayanum/Salter overrides. (4) OL gate reading (Phase 4). (5) §9 FTN 2021 trap revision. (6) Sleeper scoring deferred. (7) Builders rebuild all seasons every run (~10 min). (8) Route-tree panel has no source. (9) `mart_resolution` not built. (10) Sack tiles pending (7b decision).

## Phase 9 — DD Fantasy Football Trinity — GATE MET 2026-10-01 (Windows, same session)

### What the source turned out to be (found by driving the logged-in page, 2026-10-01)
- The page is a Supabase app behind a free member login. It serves **no stored weekly score**: for any week selection other than all 17, the browser computes the Trinity Score from `trinity_ftn_aggregates_weeks(p_season, p_weeks)` (per-player FTN counts; **`sleeper_id` and `player_gsis_id` on every row**, no nulls/dupes in 2025 wk1's 316 rows). For all 17 weeks it shows DD's stored season score, `gated_trinity_scores(_season, ...)`, 250 rows a page, `sleeper_id` on every row. (My first read, "season scores only", was wrong: Turon pointed out that the score changes with the week filter. Confirmed: 2025 wk1 only, top = Nacua 8.53, Flowers 8.51, Smith-Njigba 8.46; full season Smith-Njigba 9.13.)
- The site's own pickers give the scope: **seasons 2021–2026, REG weeks 1–17** (week 18 and playoffs are not offered). Reads are quota'd per account (`read_quota_exceeded`).
- No export exists (`AdminExportButton` is admin-only). A direct call with the site's API key pulled from its bundle was refused by the permission check and was not pursued; the page's own responses were observed instead, and the loader needs the public key in `.env`: the NEW-format `sb_publishable_…` value of the `apikey` header (not the 1,000-character `authorization: Bearer` session token, which is a personal credential and gets a 401).

### Built
| Piece | Where |
|---|---|
| Client | `fdb/ddff.py`: Supabase password login, bearer RPC, re-login on 401, quota/permission errors named, 250-row paging, credentials never recorded in raw params |
| Loaders | `ddff.trinity_aggregates` → `core_trinity_ftn_aggregates` (week grain, REG 1–17, 2021+, source names verbatim, one raw file per season-week); `ddff.trinity_scores` → `core_trinity_scores` (season grain, **closed seasons only**). Contracts in `contracts/ddff.*.fields`; `schema/022` |
| Framework | `Loader.max_week` and `Loader.closed_seasons_only` (default off; existing loaders unchanged), honoured by `scopes()` |
| Score | `fdb/trinity.py` ports the page's function line by line (z-scores of first downs, YPRR, YAC/g, rec/g, air-yard share over the WR+TE pool, clamp ±2.5, weights .36/.30/.34/.38/.29, JS `Math.round` half-up, sample std, tier bands). Builder `trinity.build` → `mart_trinity_week` and `mart_trinity_through_week` (season to date). **Derived, DD's formula as ported, never a core field.** `gsis_id` is joined through `player_ids(sleeper)`; DD's own gsis is kept and disagreement is counted and fails above 2% |
| Weekly job | both loaders and the builder are registered (`weekly = true` / builder): in `fdb weekly` in the same phase |
| Tests | 164 total (32 new in `tests/test_trinity.py`: hand-computed pool, JS rounding, clamp, filters, window sums incl. DD's team-air-yards rule, client auth/quota/401, scope limits, defects never offered, partial/truncated/odd weeks refused, idempotency, id joins, season-to-date stops at a gap, builder rollback) |

### Loaded (live DB, 2026-10-01; ~125 account reads)
`core_trinity_ftn_aggregates` 83 season-weeks (2021–2026 wk3, 24,119 player-weeks), `core_trinity_scores` 2021–2025 (1,396 rows), `mart_trinity_week` 18,685 player-weeks, `mart_trinity_through_week` 27,921. Both loaders idempotent (`fdb check`); `weekly.run_loader` for both + `trinity.build`: rc 0 (2026 wk3 loaded as it settled). 164 tests.

### Found (each is DD's data or behaviour, measured; none was assumed)
1. **DD's own data is defective in five weeks, which the loader's checks refused and which are now documented, never fetched** (`SOURCE_DEFECTS` in `fdb/loaders/ddff.py`; `Loader.unavailable`): **2021 wk15** has 25 of 32 teams (ARI-DET, DAL-NYG, ATL-SF, NO-TB absent); **2024 wk14–17** are DOUBLE-COUNTED (one-week request returns `games = 2`; Kelce 72 routes vs 44 the week before). DD's own 2024 1–17 window is inflated by it (Kelce 119 rec / 1,034 yds; actual about 97 / 823), so **DD's 2024 Trinity numbers are wrong at the source**. Season-to-date therefore ends at 2024 wk13 and 2021 wk14 (it never bridges a gap). Re-test with one read each if DD says it fixed them.
2. `player_air_yards`, `rec_yards` and `yac` are legitimately negative (2,933 / 266 / 128 rows); my first plausibility check wrongly refused them. Counts are still checked non-negative.
3. `sleeper_id` is NULL on 24 weekly rows (2021–2023) but `player_gsis_id` is always present, so the gsis id is the key and sleeper is optional.
4. **DD's stored season score is built by NAME**: the same Sleeper id sits on two rows ("Tank Dell"/"Nathaniel Dell"; 6 ids in 2023, 5 in 2024) and 7 rows have no id. Stored verbatim, keyed `(season, player_name, position, team)`; the mart compares only ids that appear once.
5. **One id disagreement across 18,685 player-weeks:** DD row "Ryan Izzo", sleeper 5094, carries Tyler Conklin's gsis (00-0034270); `player_ids(sleeper 5094)` = Izzo's (00-0034439). The exact-key join resolves it correctly; DD's own gsis is kept in `player_gsis_id` and the check fails the build above 2%.
6. 10 player-weeks (0.05%) have no `player_ids` row for their sleeper id: `gsis_id` NULL, never guessed.

### Gate
- ✅ **Port parity, 2025 wk1:** all 15 top scores equal the page's (Nacua 8.53 … McBride 6.97) and the first four tier counts (4/18/37/32) match. ⚠ **247 qualifying / 156 Depth vs the page's 246 / 155: one extra Depth player, unexplained.** The pool and scores are identical (an extra pool member would shift every z), so it is a display filter the page applies after scoring (likely its default PPG 0–30 or age 18–45 range); not verified.
- ✅ **Additivity, 2025 and 2023:** my per-week sums equal DD's own `p_weeks=1..17` call on every field once `team_air_yards` is modelled as DD does (the latest team's air yards over EVERY window week, including weeks the player missed: 480 single-team + 19 traded players, 0 exceptions), and the scores, tiers and position ranks of my season-to-date mart equal the port run on DD's own 1–17 rows for all 366 / 364 players. Ranks among tied scores follow DD's row order (ascending gsis id).
- ℹ **Ported score vs DD's STORED season score** (full 17-week windows, ids stored once): n=825, median |diff| 0.010, max 1.41 (Joshua Palmer 3.40 vs 4.81, Rashid Shaheed 6.14 vs 4.92). They agree for most players and not for all, so the stored number is **not** the live formula for every player. Both are kept, labelled: `core_trinity_scores` = DD's published season score, `mart_trinity_*` = the page's formula. Treat the mart as the weekly series and `core_trinity_scores` as DD's headline season number.
- ✅ **`fdb rebuild` ×2 → identical `ed812637…e897`, 0 network calls** (2026-10-01 09:25 and 09:36; each loads 83 `ddff.trinity_aggregates` + 5 `ddff.trinity_scores` scopes and builds `trinity.build`; wishlist exported and re-imported both times). ✅ 164 tests.

**OPEN ITEMS (new):** (11) the 247-vs-246 Depth player. (12) Trinity covers WR/TE/RB only; 2020 and earlier are not offered by the site. (13) The 2024 weeks 14–17 and 2021 wk15 source defects: nothing to fix on our side. (14) The weekly job now makes ≤ 3 reads (in-season weeks are re-fetched until the season closes, ≤ 17) against the account's quota.

## Phase 9b — Trinity on the Player Dashboard — BUILT 2026-10-01 on branch `trinity-clean` (Windows, same session)

Turon: "do both [panel and tile], replace Inside-20 Targets, all seasons".

### Built
| Piece | Where |
|---|---|
| WR tile 9 | `app/dashboard.py`: **Inside-20 Targets -> Trinity Score** (kind `trinity`, 2 dp). Value = season to date at the season's last scored week, from `mart_trinity_through_week` by `gsis_id`; percentile vs the WR pool via the existing `_percentile`; sub-line `Elite · WR1 · thru wk 3`. Seasons before 2021 show `—` / "Trinity data starts in 2021"; a receiver under DD's target floor shows `n/a` with the reason. **TE and RB tiles are unchanged** (Inside-20 only existed on WR; swap one if you want a Trinity tile there too) |
| Panel | `GET /api/dashboard/trinity?player_id&season` + `frontend/src/components/TrinityTrend.tsx`, under Snap Trend, for WR/TE/RB only: each week's score (dots coloured by tier), the season-to-date line, DD's tier bands for the position (RB use the WR bands), hover detail (targets/rec/yards/TD, week rank), the season-to-date headline with tier and `WR1 of 162`, and **DD's own published season score beside it** (labelled; it differs from the ported formula for some players). All seasons the data has (2021+) |
| Withheld weeks | Weeks the league played that DD's data lacks (2021 wk15, 2024 wk14-17; derived from the marts, not hard-coded) are hatched and named, the line stops instead of bridging them, and a warning says why. Weeks with no row for a player (bye, out, under the floor) are gaps, never zeros |
| View | `schema/024_mart_trinity_dashboard.sql`: `mart_trinity_season_stored` (apps read marts only). Keeps only sleeper ids DD stored ONCE in a season; DD builds its stored score by name, so an id on two rows is ambiguous and gets no stored score. **Numbered 024 on purpose: 023 is reserved for a migration on another in-flight branch** |
| Bundle | rebuilt with `vite build` into `app/static/viz` (the same flow as before; `tsc -b` still reports the pre-existing html2canvas CDN import at PlayerDashboard.tsx:219, nothing else) |
| Tests | 174 total (10 new, `tests/test_trinity_dashboard.py`: tile spec and unchanged TE/RB/QB, series/summary/stored, bye = gap, withheld weeks named, ambiguous stored id dropped, TE vs WR bands, QB unsupported, pre-2021, no-score player, tile value/sub-line) |

### Verified in the browser (worktree app on :5002 against a COPY of the live DB; the live DB was not touched)
Smith-Njigba 2026: tile 8.82 Elite · WR1 · thru wk 3, percentile 100, panel with 3 weeks. 2024: panel 7.85 Elite WR11 of 169 with DD's 8.10 beside it, weeks 14-17 hatched and the warning, hover on week 5 reads "4.88 · Depth · WR54 that week · 7 tgt · 4 rec · 31 yds · 1 TD, season to date 7.15". Bowers (TE) 2026: panel, no tile (as designed). Josh Allen (QB): neither, and no Trinity request is made. The only console errors are `/gameday/live` 404s (the widget was never ported, Phase 8 note). **No change to any table or builder, so `fdb rebuild`'s content hash is unchanged (views are not hashed); not re-run.**

### Merge notes
Touches `app/dashboard.py`, `frontend/src/{lib/dashboardApi.ts,pages/PlayerDashboard.tsx,components/TrinityTrend.tsx}`, `app/static/viz/*` (regenerated bundle: merge by rebuilding, not by hand), `schema/024`, tests and this log. Any other branch that regenerates `app/static/viz` conflicts with it, so **whichever merges second must re-run `npm run deploy` (vite build + copy)**.

## Phase 10 — FTN Fantasy team DVOA — LIVE 2026-10-01; gate met: app wired, `fdb rebuild` ×2 identical (Windows, same session)

### What the source is (found by reading the page's own bundles, 2026-10-01)
- `ftnfantasy.com/nfl/stats` is a React app over an AWS API. Logged out, every stats call is 401 and the table stays empty. **The FTN Data API (`data.ftndata.com`, `FTN_API_KEY`) has no DVOA** (guessed paths all 403 at the gateway; not brute-forced).
- Login: `POST api.ftnfantasy.com/users/login {email,password}` -> `access_token`; stats: `POST …execute-api…/Statshub/statshub/dvoa/team` with `Authorization: Bearer` and the page's whole default filter object (`year`, `weeks`, `seasonType` set). Credentials are `FTN_USER` / `FTN_PASS` in `.env` (v1 notes called them "unused"). `/dvoa/defense` is byte-identical to `/dvoa/team` (2025 wk5), so only `team` is read. Per-player DVOA exists (`dvoa/player`), not loaded.
- A one-week request answers one row per team that PLAYED (bye teams absent), `games = 1`. Seasons 2018+ (2016–17 answer `[]`). Week numbers run 1–22 (playoffs from 19); `seasonType: "post"` did not change the answer, so **REG only** for now.

### Built
| Piece | Where |
|---|---|
| Client | `fdb/ftnfantasy.py`: login, bearer POST, re-login once on 401/403, courtesy gap, retry on 429/5xx; credentials/tokens never in raw params |
| Loader | `ftnfantasy.dvoa_team` -> `core_ftn_dvoa_team_week` (`schema/023`), one raw file per season-week, source field names verbatim (camelCase kept), contract `contracts/ftnfantasy.dvoa_team.fields`; in the weekly job (`weekly = true`) |
| Checks | exact team coverage vs the schedule (FTN's `ARZ/BLT/CLV/HST` resolve through `team_aliases`), `games = 1`, no NULL DVOA, \|DVOA\| ≤ 3, league mean offense DVOA within ±0.5 of zero |
| Mart | view `mart_team_dvoa_week`: the one rename (`off_dvoa`, `def_dvoa`, `total_dvoa`, …) and the franchise code |
| Tests | 181 total (17 new, `tests/test_ftnfantasy.py`) |

### Loaded (live DB)
4,318 team-weeks over 143 weeks, 2018–2026 wk3. Idempotent on every week (`fdb check`). `weekly.run_loader` rc 0 (3 in-season weeks re-fetched; in-season weeks are never final because DVOA is re-adjusted, closed seasons are).

### Found
1. **2022 week 5 is missing at the source**: `[]` for a one-week request (three fetches), and a weeks 1–5 window counts 4 games. Recorded in `SOURCE_DEFECTS`, never offered or fetched. (I first read the 17-week 2022 total as a cancelled game; it was this gap.)
2. **`defDvoa`: lower is better** (DVOA convention). `totalDvoa = offDvoa − defDvoa` exactly (max error 0.0). League mean is ≈ 0 in every season (−0.002 to −0.009), which is what a correct zero-sum DVOA looks like.
3. **`offVoaUnadj` is 0 in all 4,318 rows**; `defVoaUnadj` is populated. Stored verbatim; do not read `off_voa_unadj`.
4. **`wins`/`losses` are not the real result**: on 2025, 37 of 530 non-tie rows disagree with the schedule, all one-score games (e.g. BUF 41–40 BAL gives BAL the "win"). They look DVOA-based. Do not use them as records.
5. **These are single-week values.** Season-to-date DVOA is FTN's own opponent-adjusted number for a multi-week window, not a sum or average of these (rule 4). For an app window, weight by plays: `SUM(dvoa*plays)/SUM(plays)` with plays from `mart_team_off_env_week` (offense) and plays faced (defense). Not built yet.
6. **A concurrent `fdb rebuild` clobbered the first backfill.** A rebuild running in another session was building its side DB from raw while I loaded; its swap at 09:36:51 replaced the live file with a build made before this loader existed, leaving the table empty. The pre-swap snapshot still had all 4,318 rows. Recovered by reloading from raw (no network for closed seasons). Lesson for the next session: check for a running `fdb rebuild` (side file `database/fdb.rebuild.db`, new `pre_rebuild_*.db`) before any DB write.

### Gate
- ✅ Loader idempotent; `fdb weekly` path rc 0; field-name check; plausibility checks; tests.
- ✅ **`fdb rebuild` ×2 → identical `994afb1bfb54fbf823276a951e49b3ef82d49564b4e49f21a7350be3f62732eb`, 0 network calls** (2026-10-01, run on `main` with Phase 9 and 10 merged; exit 0 both times, no FAILED scopes, the two reports identical but for the snapshot name; each loads 143 `ftnfantasy.dvoa_team` scopes plus the 83 + 5 Trinity scopes; wishlist exported and re-imported both times). **This supersedes the Phase 9 hash `ed812637…e897`**, which was taken before this table existed. After the swap: 4,318 rows in `core_ftn_dvoa_team_week` and `mart_team_dvoa_week`, `integrity_check` ok, :5000 serving 200 without a restart. ✅ 196 tests.
- ✅ **App wiring done (same day, below).**

**OPEN ITEMS (new):** (18) playoff weeks (19–22): unverified, not loaded. (19) `dvoa/player` is available if wanted (QB/RB/WR DVOA). (20) **Game Day live tracker: decided NOT to port (Turon, 2026-10-02).** The front end (imported in `84bb1c7`) polled `/gameday/live`, which v1 served from `app/gameday.py` + `gameday_service.py` (live MFL/Sleeper/ESPN fetched per request); v2 has no such route, so the drawer showed "404 NOT FOUND". First hidden (the provider treated a 404 as "unavailable"), then **deleted outright 2026-10-02**: `frontend/src/gameday/`, `frontend/src/types/gameday.ts` and the mount in `main.tsx`; bundle rebuilt. (`fetchTeamDefenseGameday` in `defenvApi.ts` is a different feature, the single-week team-defense view, and stays.)

### App wiring (Team Offense / Team Defense), 2026-10-01
| Piece | Detail |
|---|---|
| API (`app/env.py`) | `_dvoa_rows/_dvoa_window/_dvoa_block`: weekly `mart_team_dvoa_week` joined to that team-week's plays (`mart_team_off_env_week` split `all` for offense; `def_plays` for defense). Any week range = `SUM(dvoa*plays)/SUM(plays)` over the weeks that have both (rule 4); the per-week trend is the raw weekly value; league median per week. Offense: `header.dvoa`, `trend.dvoa`, `trend_league_median.dvoa`, `league_table[].dvoa`. Defense: the same with `def_dvoa` (rank inverted: lower is better) |
| Front end | Header chip, trend card and a sortable league-table column on both pages ("DVOA" / "DVOA allowed", shown as +x.x%). Types in `lib/offenvApi.ts`, `lib/defenvApi.ts`. Built with `vite build` and copied to `app/static/viz` (`tsc -b` has one existing error, `PlayerDashboard.tsx` imports `esm.sh/html2canvas-pro`; none in the changed files) |
| Verified | Flask test client: a one-week window equals the raw weekly value (KC wk7 0.2611 / −0.3049); KC 2025 season 0.053 weighted vs 0.036 plain mean. Live :5000 after restarting the app process: BUF 2026 wks 1–3 shows offense DVOA +37.0% (#2/32) and DVOA allowed +3.4% (#21/32); both match a hand calculation from the DB (52/66/62 plays; 73/62/64 plays faced). 186 tests |
| Notes | The number is **play-weighted weekly DVOA, not FTN's own opponent-adjusted season DVOA** (FTN's multi-week figure cannot be rebuilt from single weeks); the tiles and column say "DVOA" and this log is where the difference is written. 2022 wk5 has none (source gap), so a 2022 season figure covers 17 weeks. |

## Phase 11 — Matchup of the Week: data + card — DATA LAYER BUILT 2026-10-03 (Windows, same session); mart, projections and render NOT built

Turon asked for a redesign of the v1 Discord "Matchup of the Week" card after its week-4 post (Steelers vs Bengals, 30590) showed records 0-0, scores 0.00, "FINAL" and an all-time series built from partial history. Kickoff prompt `PHASE11_PROMPT.md`; design reference `docs/matchup_card_mockup.html` (real figures from this phase's data; win probability and position-board edges still v1's). **Decided by Turon: the featured game is the picked pairing (v1's selector), card shows that pairing only.**

### Causes found by reading v1 (not run)
(1) `_records`/`_series` read cache only (`fetch=False`); (2) `mfl_weekly_results` caches any non-empty payload 30 days, including an in-progress week; (3) wins counted only from MFL's `result` flag; (4) `scouting_weekly_job.py` uses the auto-detected CURRENT week for the recap as well as the preview, so a Monday recap targeted unplayed week 4; (5) the card never checks game state; (6) prose is generated separately from the numbers.

### Live probe facts (each measured on league 30590)
- **Each franchise plays TWO games a week** (32 franchises, 32 matchups, same score in both games; 2026 after wk3 = 6 games: Steelers 4-2, Bengals 5-1). Count games per row, points once per week.
- An unplayed week has no `score`/`opt_pts` and `result` = "T" for every franchise.
- `projectedScores` is per-player per-week (v1's 100+ player values are real: this league scores big, team weeks 650-1,170). My first suspicion that v1 showed whole-roster values was wrong. Steelers' projected starters wk4: 1,268.37 vs Bengals 1,360.19 (v1's card said a 28.03 gap; unexplained).
- The league began in **2020** (MFL: Invalid league ID for 2019); field names are stable 2020-2026 (`comments` extra in 2020, `adj_score` in 2021).
- Starters' scores + `adj_score` equal the franchise score exactly in every loaded week (2021 wk1: two franchises carry a -1000 commissioner adjustment, already inside `score`).
- `h2h = ALL` (TWE 55757) has no matchups; fantasy playoff weeks after the bracket is decided have none either (30590 2020 wk17; 46276 and 60398 2025 wk18).

### Built
| Piece | Where |
|---|---|
| Loaders | `mfl.weekly_results` -> `core_mfl_weekly_results` (one row per franchise PER GAME: `id`, `opponent_id`, `isHome`, `score`, `adj_score`, `result`, `opt_pts`); `mfl.lineups` -> `core_mfl_lineups` (franchise-week-player: `status`, `shouldStart`, `score`), reading the first loader's raw (one fetch, two tables). `schema/025`, contracts `mfl.weekly_results.fields`, `mfl.lineups.fields`, registry rows, both `weekly = true` (fetcher before reader) |
| Framework | `League.history_seasons` + `Loader.history`: the config's EXTRA closed seasons (30590: 2020-2024) are read only by loaders that opt in (`mfl.league/divisions/conferences/franchises/weekly_results/lineups`); `player_scores`, `rosters` etc. still read only `seasons` |
| Checks (in the transaction) | every row has a score; each game has a mirror row; `result` agrees with the scores; one franchise = one score across its games; franchise ids exist in `core_mfl_franchises`; |score| <= 5000; lineups: `starters` = players marked starter, a franchise's games share one lineup, starters' scores + `adj_score` = score, same franchise count as results. Non-h2h leagues offer no weeks; an empty week is valid only after `lastRegularSeasonWeek` |
| Tests | 24 new (`tests/test_weekly_results.py`); suite 220 |

### Loaded (live DB)
`core_mfl_weekly_results` 9,990 rows, `core_mfl_lineups` 424,543 rows, 188 scopes each: 30590 2020-2026 wk1-3, and the other leagues' 2025-2026 (TWE excluded). League history 2020-2024 for `league/divisions/conferences/franchises` (32 franchises, 8 divisions each). A snapshot was taken first: `database/pre_phase11_20261003.db` (gitignored). MFL 429'd twice during the backfill (heavy endpoint, 3 s spacing); the framework's cooldown + re-run finished it with no manual edit.

### Gate
- ✅ Both loaders: contract recorded from live responses; idempotent (`fdb check --loader`); in `fdb weekly` (registered; the first scheduled run is Wed 2026-10-07 05:00); live runs OK.
- ✅ **Records vs MFL's own standings (30590 2025, regular season weeks <= 13): W-L-T identical for all 32 franchises (26 games each).** Points: MFL's `pf` is NOT comparable (it counts every game, playoffs included, and appears to include a week where the franchise has no matchup row; not verified), so "points for" on the card is defined here as each regular-season week counted once. 2026 through wk3: Steelers 2,680.95, Bengals 2,854.35.
- ✅ **Series, Steelers (0029) vs Bengals (0003), 2020-2025 regular season: 13 meetings, Pittsburgh 4-9; last meeting 2025 wk4 1,019.15 to 779.55 (equals v1's own "last meeting" line).** v1's "tied 1-1, 2 meetings" was its cache gap.
- ✅ **`fdb rebuild` x2 -> identical `5a36ccbe35da5d3b925044d50f3f59d961271255f6c1bc64e096e0719dfde751`, 0 network calls**, `integrity_check` ok. This supersedes the Phase 9+10 hash. 220 tests.
- ⏳ Not yet: the 3-rivalry hand check beyond Steelers-Bengals; a Turon review of rendered cards.

### Projections loader (same day, same session)
`mfl.projected_scores` -> `core_mfl_projected_scores` (`schema/026`): per-player per-week projections under the league's scoring, **one snapshot per fetch** (`snapshot_at`), the next unplayed regular-season week only, in `fdb weekly`. Framework: `Loader.snapshot_bases` (default unchanged) lets a `league_snapshot` loader carry a week.
Live findings, each measured: (1) **projections are league-scored** (Gibbs wk4: 142.25 in 30590/60398, 27.49 in 46276; leagues with the same rules answer identically), so the table is per league; (2) an UNPLAYED week's projections move (20 of 1,006 players changed within hours); (3) **a list fetched AFTER the games is partial: 30590 wk3 has 895 players against 1,007 for wk4, and 166 of 896 starters (scoring up to 91) have no projection.** So a post-game fetch is not the pre-game projection: completed weeks are NOT fetched and nothing is flagged final; a reader takes, per week, the last snapshot BEFORE the week's first kickoff; (4) every response ends with one `{"id": "", "score": ""}` placeholder, found by a NOT NULL failure on the first live load (rolled back, nothing written); it is dropped, while a score with no id is refused. Sanity: wk3 starters' projected totals vs actual, 30590: corr 0.894 (projections run ~35% high; post-game list, so indicative only).
**Loaded:** 11,402 rows, 12 snapshots (6 leagues x wk3 + wk4, all fetched 2026-10-03). **The six wk3 snapshots are post-game and partial; wk4 was fetched after Thursday's game, so it is mid-week. 2026 weeks 1-4 therefore have no pre-kickoff snapshot: the first week with one is week 5 (fetched by Wednesday 2026-10-07's run), so the first recap with projected-vs-actual is week 5.** Snapshot taken first: `database/pre_phase11b_20261003.db`.
**Gate:** idempotent (`fdb check --loader`); in the weekly job; **`fdb rebuild` x2 -> identical `96ae36d820cf39046757ae3c6a0f67e09a5eec18df0234a586eae45dbe92bc12`, 0 network calls**, `integrity_check` ok (supersedes `5a36ccbe...`). 231 tests.

### Post-game data already in v2 (Turon asked for post-game stats, 2026-10-03; chose the recap card)
Actuals need no new loader: `core_mfl_weekly_results` (score, result, `opt_pts` best lineup) and `core_mfl_lineups` (every rostered player's actual score and starter/bench status). Checked on 30590 wk3, Bengals (0003) vs Colts (0013): position groups sum exactly to the final scores (1,174.0 and 982.7), 0 of 56 starters unresolved through `player_ids(mfl)`. Position codes seen: MLB, SAF, ED etc. (v1's `POS_GROUP` mapping covers them). A FINAL recap mockup was shown in the session (real wk3 data).

### Matchup card mart + upcoming-week loaders (same day, same session)
**Loaders `mfl.upcoming_games` / `mfl.upcoming_lineups`** -> `core_mfl_upcoming_games` / `_lineups` (`schema/027`): snapshots of `weeklyResults` for the NEXT unplayed week (pairings, `isHome`, lineups), so the card's PREVIEW has data (`weekly_results` only holds completed weeks). Own raw endpoint `weeklyResultsUpcoming`, because `weekly_results` keeps 3 non-final files per partition and could prune a pre-kickoff snapshot. Non-h2h leagues skipped. First live snapshot 2026-10-03 (5 leagues, wk4).
**Builder `matchup.build`** (`fdb/matchup.py`, `schema/028`) -> `mart_matchup_card` (one row per fantasy GAME, an unordered pair), `_groups`, `_players` (starters per franchise-week). Rules that matter:
- `state` PREVIEW / LIVE / FINAL comes from the SCHEDULE, never from a score or MFL's `result`.
- Records and points-for are through the weeks BEFORE this one, regular season only (`week <= lastRegularSeasonWeek`), every game counted, a week's points once. Series = regular-season meetings of the same franchise ids in all loaded seasons, strictly earlier. **Franchise id = same owner across seasons is assumed, not audited.**
- Projections: the LAST snapshot before the week's first kickoff, else NULL (never guessed). A pre-game list is preferred to the partial post-game one.
- Players join through `player_ids(mfl)` only; an unresolved id keeps its MFL id and no name. Position codes map to groups (v1's `POS_GROUP` plus K/PK); MLB, SAF, ED etc. covered.
- `config/franchise_colors.toml`: accent + alternate color per franchise id, 30590 only (32 clubs); v1's name lookup was too dark/too similar (Ravens, the three oranges).
- Checks roll the build back on: unknown `result`, FINAL with a missing score, record counts that do not add up, groups total != starters total, starters' actuals + `adj_score` != reported score, > 1% starters with no position group, bad color config. A real 0.00 (a franchise that set no lineup, 25 FINAL games) is allowed because the starters reconcile to it, and is counted.
**Live build:** 5,194 games (FINAL 4,995, LIVE 199 = wk4 pairings), 41,919 group rows, 189,534 starter rows, 76 ungrouped starters (devy college ids 0800-0999 in the two devy leagues, one NFL id). Spot checks: Bengals v Colts wk3 FINAL (3-1 v 1-3 before the week, Bengals 1,174.00 to 982.70, series CIN 5-1); Steelers v Bengals wk4 (CIN 9-4 in 13 meetings, last 2025 wk13 926.80 to 804.95, rivalry flag set). Snapshot first: `database/pre_phase11c_20261003.db`.
**Gate:** **`fdb rebuild` x2 -> identical `6df3474ccb3b27f7dfc8a1c00f3659e86d7b6342dc7d58f4e8ba7f293a7ca98e`, 0 network calls**, `integrity_check` ok (supersedes `96ae36d8...`). 253 tests at the mart commit (`f01202f`), 277 with the page below.

### Review page `/matchup/` (built, not committed at the time of this entry)
`fdb/matchup_card.py` (data + HTML, reads `mart_matchup_card*` only, shared with the future Discord job) and `app/matchup_card.py` (`/matchup/` page; `/matchup/card/` card only; `/api/matchup/games`, `/api/matchup/card`). Review only: it writes nothing and sends nothing. Cards are labelled projected or actual and never mix them: a FINAL card uses actuals (winner tag, margin, bench points left, top performers); PREVIEW/LIVE cards use pre-kickoff projections, a win-probability bar (v1's logistic of margin over 5% of the combined projection, NOT calibrated: the card says "projection edge"), a position board and players to watch; with no pre-kickoff projection those panels are omitted and a note says why (today: all of week 4). Colors: configured pair, the away team's alternate when two primaries are within RGB distance 90, a fallback pair otherwise. All database text is HTML-escaped and only http(s) logo URLs are used (MFL-hosted images; the renderer will embed them). Verified in the browser on real data (wk3 FINAL, wk4 LIVE). 24 tests (`tests/test_matchup_page.py`). `app/theme.py` was left byte-identical (the page uses the default accent).

### Featured-game picker (2026-10-04, same phase)
`fdb/matchup_pick.py`: a port of v1's `pick_matchup` scorer (Turon chose "the picked game" = v1's selector), reading `mart_matchup_card` only. Per game: quality of each team = `w*(wins/games) + (1-w)*prior`, `w = games/(games+6)`, `prior = 0.6*pedigree + 0.4*roster-strength rank` (strength rank alone when there is no pedigree); pedigree = last season's win% and points-for ranks (0.7) plus the playoff result (champion 1.0, finalist 0.85, 0.3), min-max normalised; score = `0.45*min(quality) + 0.25*closeness + 0.10*size + 0.10 (both > 0.5) - 0.40*|quality gap|`; the top score is featured. Deterministic (ties by franchise ids). The formula and the pedigree are tested against HAND-COMPUTED values, not a copy of the code.
**Deliberate differences from v1** (also shown on the page): (1) projections and strength come from the last snapshot before the week's first kickoff, so a Thursday preview and its Wednesday-night recap pick the same game; (2) last season's win% and points-for come from the mart's completed games (regular season, a week's points once), not MFL's standings, and ranks are used so the effect is small but not zero; (3) `basis`: with no pre-kickoff projection a FINAL week is ranked from what happened (starters' actuals as the projection, the whole lineup's actuals as strength), otherwise from records and pedigree alone (closeness and size dropped); the page names the basis.
`schema/029` adds to `mart_matchup_card`: `is_playoff` (129 bracket-week games), `*_strength` (whole-lineup projection, NULL until a pre-kickoff snapshot exists), `*_roster_actual` (FINAL only). The page lists games in picker order, stars the featured one, adds the "Matchup of the week" pill to its card and a "why this game" note. 31 tests (`tests/test_matchup_pick.py` plus the page tests).
**Parity with v1 could NOT be shown.** v1 featured Steelers v Bengals for wk4 (posted 2026-09-29), but its inputs are unrecoverable: its records were all 0-0 (the cache bug), its projections were Monday's, and with lineups unset it summed the whole roster. A diagnostic on the only wk4 snapshot we hold (taken after Thursday's game, so Thursday's players are already missing) ranks Steelers v Bengals 3rd with real records AND with records zeroed. So the formula is verified by hand arithmetic, not by reproducing v1's pick. Live today, with no pre-kickoff projection for wk4, the pick is records-only (Raiders v Chiefs).
**Gate:** **`fdb rebuild` x2 -> identical `d4bc3c09f32b002a9b4cb4cd5b09371b2b6dce6bc72c7fc89e090aae4f9141f7`, 0 network calls**, `integrity_check` ok (supersedes `6df3474c...`). 292 tests (commit `9d2cfd0`).

### PNG renderer (2026-10-04, same phase; no table, builder or schema change, so the rebuild hash `d4bc3c09...` is unchanged)
`fdb/card_render.py`: the card's HTML (`fdb/matchup_card.py`) screenshot by headless Chromium through Playwright at 2x (the 3.13 interpreter already has `playwright` 1.61 and its Chromium; v1 used the same route). Output 1,364 x about 2,200 px, ~400 KB. Three ways to get it: `python -m fdb card [--league --season --week --home --away --out]` (default: the newest week's FEATURED game, written to `data/cards/`), `/matchup/card.png?...` (rendered on request, `no-store`, linked from the review page as "the image that would be posted"), and `card_render.render_png(card)` for the future job. **It never posts anything; the CLI says so.**
- **Logos** are downloaded once through `fdb/http.py` (the only network path), cached in `data/cache/logos`, identified by their magic bytes (the server's content type is not trusted; HTML is refused), capped at 1.5 MB, and embedded as data URIs, so a render never depends on a live fetch and Discord never fetches anything. A logo that cannot be had (404, network off, not an image) is absent and the card falls back to its abbreviation ring; a failure is remembered for a day. The renderer's `_logo` accepts only http(s) URLs or PNG/JPEG/GIF/WEBP data URIs. `data/cards/` and `data/cache/` are gitignored.
- **A render that cannot run raises `RenderError` with the reason** (Playwright missing, Chromium failed, no data, no such game); the route answers 503 with it. It never returns a blank image.
- First real render, Bengals v Colts wk3 FINAL: the Colts' MFL logo is embedded as the watermark; **the Bengals franchise (0003) has NO logo in MFL**, so it shows the abbreviation ring. Setting a logo on franchise 0003 in MFL fixes it.
- Tests: 16 in `tests/test_card_render.py` (logo cache, sniffing, size cap, no-network, escaping, failure paths, and a real Chromium render, the CLI and the route; skipped where Chromium is missing). Suite 308.

### Week selection (2026-10-04, same phase)
**The v1 bug:** `scouting_weekly_job.py` used ONE auto-detected "current week" for both modes, so the Monday-morning recap of 2026-09-29 targeted unplayed week 4 ("Week 4 recap", 0.00, FINAL). `fdb/matchup_weeks.py` answers the two questions separately, from `mart_matchup_card` only, never raising and never writing:
- `recap_target`: the LATEST week whose results are loaded (every game FINAL). While a later week is in progress (or finished but not loaded yet) it still answers the previous week and `waiting_for` names the later one, so a job can see why nothing new is ready.
- `preview_target`: the EARLIEST week that has not kicked off (PREVIEW). A week that has kicked off is `ready: False` with "already kicked off; a preview has to be rendered before kickoff". It reports `projected` (was a projection captured before kickoff?) because a preview without one has no projected panels; the caller decides whether to post.
- A league or season that is NAMED but has no data answers "no matchup data for league X", never another league's week (a first version silently fell back to 30590; caught on the live data with league 55757 and fixed).
**Live today (2026-10-04):** recap = week 3 (ready; week 4 in progress); preview refused (week 4 kicked off 2026-10-01). So there is no postable preview until Wednesday's run fetches week 5.
**Surfaces:** `python -m fdb card --mode recap|preview` (refuses with the reason instead of rendering the wrong week; cannot be combined with `--week/--home/--away`); `render_to_file(mode=...)`; the review page's "WHAT A JOB WOULD POST" box with links.
**A related builder bug found and fixed:** a week complete per the schedule but whose results the weekly job had not loaded yet (Wednesday 00:15 to 05:00 ET) was labelled FINAL with no scores, which fails the build's "FINAL with a missing score" check and rolls the whole mart back (a `fdb rebuild` in that window would have failed). **FINAL now means the results are LOADED**; such a week stays LIVE, is counted in the build summary ("awaiting their results"), and the recap waits for it. Tested with a week finished in the schedule but not loaded, then loaded.
**Verification:** the three mart tables are byte-identical (table hashes) to the rebuilt gate state (`d4bc3c09...`), so the change alters no current output; **no full `fdb rebuild` was run** because the working tree also holds ANOTHER SESSION's uncommitted injuries work (`fdb/loaders/injuries.py`, `schema/030_core_injuries.sql`, contracts, registry and `loaders/__init__.py` edits; migration 030 is already applied to the live DB), which would change the hash and could collide with it. Run the rebuild x2 gate after that work lands. 324 tests (one `test_rebuild` error appeared once while those files were mid-edit and did not recur).

**Not built (next):** the Discord post itself (a webhook; `OPS_DISCORD_WEBHOOK` unset; per-run explicit approval; nothing has ever been posted) and its idempotency log (one post per league, week and mode).

**OPEN ITEMS (new):** (21) Phase 11 remainder, above. (29) Picker parity with v1 is unproven (above); revisit when a week has a real pre-kickoff snapshot (week 5) and compare against what Turon would have chosen. (27) The page's win probability is v1's uncalibrated logistic; calibrate it against results before it is shown as a probability. (28) `fdb rebuild` now takes ~12 min (the two of this session ran 21:48 to ~22:25). (26) The weekly job fetches projections once a week (Wednesday), which is the only pre-kickoff snapshot before Thursday's game; a Thursday-morning preview would use it. Add a daily/Thursday fetch if fresher injury news is wanted (`ops\daily_rosters.bat` is the model). (22) v1 Scouting tasks keep posting the broken card until replaced. (23) Turon: should the card's "points for" be the once-per-week total (2,681) or MFL's per-game figure? (24) The weekly job now fetches `weeklyResults` for 5 MFL leagues (not only 30590); empty playoff weeks are re-fetched each run (never final). Say if only 30590 is wanted. (25) Franchise id -> owner stability across 2020-2025 is assumed from MFL ids (names match for 0003/0029); not audited for all 32.
