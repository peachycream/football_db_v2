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

**NEXT: Phase 2 — nflverse core** (spec §8): player stats, snap counts, pbp, participation 2016–2025, NGS, ff_opportunity; all in the weekly job; parity vs the v1 oracle on 2024. Check asset formats first — `load_pbp`/`player_stats` may be parquet-only, which would bring in `pyarrow` (first non-stdlib dependency; decide deliberately).
