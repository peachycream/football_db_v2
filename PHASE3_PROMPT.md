# Phase 3 kickoff — run LOCALLY on Windows

The cloud container can't reach MFL or Sleeper, and the gate needs the v1 database, so Phase 3 runs in a **local** Claude Code session on the Windows machine. Paste everything below the line as the first message.

---

You are starting **Phase 3 (Fantasy + Ownership)** of `football_db_v2`. Read `CLAUDE.md`, `REBUILD_DESIGN.md` and `REBUILD_LOG.md` in full first. They are the contract; Phases 0–2 are done and gated. Do not re-derive them.

## 0. Local setup (first time on Windows — do this before any Phase 3 code)
1. Clone `peachycream/football_db_v2` next to v1 (e.g. `C:\Users\k-ble\football_db_v2`) if not already cloned.
2. Create `.env` in the v2 root with **only** what v2 needs: `MFL_USERNAME`, `MFL_PASSWORD` (copy the values from v1's `.env`, never the whole file), and later `OPS_DISCORD_WEBHOOK`. Confirm `git status` does not show it.
3. Interpreter: `"C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"` (call it PY). `cmd.exe`: no `&&`.
4. `PY -m unittest discover -s tests -t .` → all pass. **This is the first run on Windows.** Path, encoding (`PYTHONIOENCODING=utf-8`) or timezone surprises get fixed here and logged.
5. Populate data: `PY -m fdb weekly` (fetches Phases 0–2; about 800 MB, a few minutes), then `PY -m fdb reconcile --season 2024 2026` → all ok.
6. v1 is the **read-only oracle**: `C:\Users\k-ble\football_db\database\football.db`. Open it with `sqlite3.connect("file:...?mode=ro", uri=True)` only. Never write to it and never copy data from it into v2, **except** the user-entered wishlist (step 3.6).

## 1. Leagues in scope (from v1 `gameday_config.json`, the "who am I" registry)
| platform | league_id | name | my franchise |
|---|---|---|---|
| mfl | 30590 | TINO NFL Elite | 0021 |
| mfl | 57653 | TNT Devy | 0001 |
| mfl | 46276 | NFL Flex It Up | 0006 |
| mfl | 60398 | TINO March Madness | 0061 |
| mfl | 55757 | TWE | 0003 |
| mfl | 60856 | TINO NCAA | 0005 |
| sleeper | 1312225799826325504 | The Gamers Dynasty | roster 11 |
| sleeper | 1312262620807454720 | Fantasy Scouts Dynasty League | roster 2 |

Put this in `config/my_franchises.toml` (checked in; nothing secret in it). **Do not include** legacy 19161 or 21991.

## 2. Source facts carried over from v1 (verify each live; don't trust them blindly)
- **MFL auth:** `GET https://api.myfantasyleague.com/<year>/login?USERNAME=..&PASSWORD=..&XML=1` → cookie `MFL_USER_ID`; pass it as the `APIKEY` param **and** as a cookie on `export` calls.
- **MFL endpoints** (`/<year>/export?L=<id>&JSON=1&TYPE=...`):
  - `league`: franchises, divisions/conferences, `rostersPerPlayer` (55757 = 2)
  - `rosters`
  - `rules`: scoring
  - `playerScores&W=<n>`: reported points; this is the IDP-calibration truth. **v1's `mfl_get_weekly_results` is misnamed: it calls `playerScores`.**
  - `players&DETAILS=1`: league-scoped devy names
- **MFL aggressively returns 429.** Every response goes through the raw store (never cached if non-final); exponential backoff. **A single-league row is NOT a cache key: key on (season, league, type, week)**. v1 once served 2025 scores as 2026 because a key didn't name the season.
- **Multi-conference leagues store one roster copy per conference pool**, so elevated roster-row counts are correct (v1 hard rule 7). Model the pool explicitly.
- **MFL JSON quirk:** a list with one element comes back as a bare object (`franchise` dict vs list). Normalise in `parse`, and test it.
- **Scoring is catch-all** (v1 `diag_proj_14`): narrow per-position rule rows are NOT overrides. League 46276 genuinely has no catch-all rows. Store rules verbatim; interpretation is a mart concern (Phase 6).
- **Known discrepancy to re-test, not fix:** v1 found 30590's stored rules disagree with MFL's own reported scores (Darnold 2025 wk1: reported 20.9, 30590 rules predict 7.60). Store both verbatim and record what you find.
- **Sleeper:** `https://api.sleeper.app/v1/league/<id>`, `/rosters`, `/users`, `/matchups/<week>`, and `/players/nfl` (~5 MB; carries `gsis_id` for many players). Sleeper rolls dynasty leagues to new ids yearly via `previous_league_id`.
- **Sleeper players → identity:** add `/players/nfl` as a new identity source, **below** nflverse and **above** DynastyProcess in `fdb/identity.py`'s precedence (it is source-native gsis). Name-check it like DP. Update the traps if anything changes.

## 3. Build (spec §4, §5, §8 Phase 3)
1. **Framework:** scopes are season-only today. Add a league dimension (e.g. `Scope.key` = league id, partition `"<season>/<league>"`) without breaking Phases 0–2. Run the existing tests after.
2. **Tables** (source names verbatim, one owner each, registered in `registry/sources.toml`):
   - `core_mfl_league`, `core_mfl_franchises`
   - `core_mfl_rosters` (**snapshot rows with `snapshot_at`**; keep history, and decide the retention)
   - `core_mfl_rules`
   - `core_mfl_player_scores` (week grain; week-complete gate applies)
   - `core_mfl_players` (league-scoped devy)
   - `core_sleeper_league`, `core_sleeper_rosters`, `core_sleeper_users`, `core_sleeper_players`
3. **Identity:** MFL roster player ids resolve through `player_ids` source `mfl`. **Every dropped/unresolved roster id is listed, never silently skipped** (v1's own_03 bug dropped 17% of slots). Devy/CFB ids that have no NFL identity yet stay unresolved and are counted separately; CFB is a later phase.
4. **Mart:** `mart_roster_ownership` (latest snapshot per league/pool, joined to `players`, flag for my franchise from `config/my_franchises.toml`).
5. **App shell:** v2 has no Flask app yet. Create `app/` with a minimal Flask app, copy the colour system from v1 (`app/static/theme.css`, `theme.js`, `app/theme.py`) as-is, and port `/ownership/` (v1 `app/ownership_search.py`: search, suggest typeahead, FA browse, wishlist) **reading `mart_*` only**.
6. **User state:** create `app_wishlist` (from v1 `draft_wishlist`) and `app_wishlist_priority` (from v1 `draft_wishlist_priority`). Import rows from v1 once, **re-keyed from v1 slugs to `gsis_id`**. Any v1 slug that can't be mapped by an exact key is listed, never guessed. Confirm the rows survive `fdb rebuild` via `app_state/`.

## 4. Gate (write results to `REBUILD_LOG.md`)
- Every MFL/Sleeper loader: contract fields recorded from a live response; idempotent; in `fdb weekly`.
- **0 silently dropped roster ids**: every roster slot is resolved, or listed as unresolved with its reason.
- `/ownership/` answers match v1 for a 50-player sample across all 6 MFL leagues and both Sleeper leagues (owner franchise per league/pool). Every difference is explained.
- Wishlist imported and survives a rebuild.
- `fdb rebuild` twice gives identical hashes with 0 network calls. Tests pass on Windows.

**Stop at the gate and report.** Say plainly that it is a clean stopping point. Don't start Phase 4.
