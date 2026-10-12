# Phase 14 kickoff — CFB / Devy tracker

> Numbering: Turon asked for "Phase 12", but Phases 12 and 13 are the alerts phases in `REBUILD_LOG.md`. This is **Phase 14**.
> Scoped 2026-10-10 with Turon (questions answered in chat). Run LOCALLY on Windows. To restart in a new session, paste everything below the line.

---

You are starting **Phase 14 (CFB / Devy tracker)** of `football_db_v2`. Read `CLAUDE.md`, `REBUILD_DESIGN.md` (§3.4 "Room for CFB later") and `REBUILD_LOG.md` first; they are the contract. Do not re-derive earlier phases.

## 0. The ask (settled; do not re-ask)
A tracker page, inside the existing Flask/React app, of the progress of devy players drafted in Turon's MFL devy leagues:
- **Highlight** players on Turon's own devy rosters; show every other owner's players as "owned by <franchise>".
- **Highlight free agents**: college players NOT rostered in that league who are producing, ranked by a fantasy-relevant production measure, with a minimum-games filter.
- **Positions:** QB, RB, WR, TE and IDP (DL/edge, LB, DB).
- **Stats:** the ones that matter for fantasy success per position (see §3), plus **height, weight, age**, class and school.
- **Sources:** CFBD (`CFB_API_KEY`) and PFF (`PFF_API_KEY`, `PFF_USER`, `PFF_PASS`). Both are already in `.env` (CFB keys copied from v1's `.env` 2026-10-10; values never printed).
- **Rosters:** one-time seed from Turon's screenshots now; swap to MFL when it exposes devy rosters.

## 1. Leagues and franchises (Turon's, 2026-10-10)
| League id | Name | Turon's franchise | Screenshot | Dated |
|---|---|---|---|---|
| 57653 | TNT Devy | WPB Wallabies | `Screen Captures/2026 57563 Devy .png` (the filename has the digits swapped; **57653 is correct**: it is in `config/my_franchises.toml` and the loaded MFL data) | 8/31/2026 |
| 60398 | (Big East names) | Georgetown Hoyas | `2026 60398 Devy .png` | 8/8/2026 |
| 60856 | (college names) | Miami Hurricanes | `2026 60856 Devy .png` | 9/9/2026 |
| 55757 | (WWE names) | Undertaker | `2026 55757 Devy .png` | 9/1/2026 |

- **League 55757 holds two copies of each player** (Turon, 2026-10-10): the same player appears under two different franchises. Store one row per (franchise, player); the "copy" is simply the second owner row. The page shows both owners for a player in that league. If a franchise lists the same player twice, flag it.
- **The screenshots are partial.** They show 12 / 28 / 11 / 11 franchises; the DB has 36 / 44 / 50 / 100 loaded for these leagues. Ask Turon whether the others have no devy players or the picture is cropped. Rows for franchises not on a screenshot are simply absent, never guessed.

## 1a. Turon's answers (2026-10-10)
- The screenshots cover only the conferences Turon's teams compete in (so 12 / 28 / 11 / 11 franchises of 36 / 44 / 50 / 100). Other franchises are simply not tracked yet; do not treat them as empty.
- **Age: blank is okay** when no source has a birthdate. Never estimate.
- **Add a draft-year-eligibility column.** Source it from PFF `eligible_season` (and `draft_season` when set); show blank, not a guess, when PFF has none. A class-year estimate is only a labelled fallback if Turon asks for it.
- Mapping approach approved: a review CSV (`data/devy_review.csv`, built by `fdb/devy_candidates.py`) of candidates with evidence; Turon's `approved_cfbd_id` is the exact key; nothing loads before approval.

## 1b. Findings from the 2026-10-10 probes (already done; do not redo)
- **All four leagues and Turon's franchises are already loaded** in `core_mfl_franchises` (2025 and 2026) and listed in `config/my_franchises.toml`: 57653 → `0001`, 60398 → `0061` (Georgetown Hoyas), 60856 → `0005` (Miami Hurricanes; MFL's name carries HTML `<font>` markup, strip it for display only), 55757 → `0003` (The Undertaker). No config change needed. The screenshot franchise names are display names; map to MFL ids via `core_mfl_franchises`, not by name matching in code: write the franchise id into the seed by hand.
- **MFL devy rosters are PLACEHOLDERS, not data (Turon, 2026-10-10).** The unmapped MFL roster ids (league-scoped, "Last, First" names, positions mostly QB) are slots that get replaced when a player is drafted to the NFL. **Never use MFL for devy mapping or as the roster source.** The screenshot seed plus the approved `data/devy_review.csv` are the source; when a player gets an NFL identity the normal `player_ids` path takes over. (An earlier note here said MFL held no devy players: wrong in detail, right in effect.)
- **CFBD works** (`https://api.collegefootballdata.com`, Bearer `CFB_API_KEY`, ~1000-call budget visible in `X-CallLimit-Remaining`). `player/search` returns `id`, `team`, `height` (inches), `weight`, `jersey`, `position`, `hometown`, `activeStartYear/EndYear`, `teamStints`. **No birthdate → no age from CFBD.** `stats/player/season` is long format: one row per `(playerId, category, statType)` with `stat` as a string; pivot in the loader, keep names verbatim.
- **PFF has college data**: `GET /v1/facet/passing/summary?league=ncaa&season=2025&week=1` returns rows with `eligible_season`, `draft_season`, `player_game_count` and the NFL-style grades; the same client (`fdb/pff.py`) works. Its NCAA team names look like codes (`NEWHVN`), so map teams by PFF's id, not name. Probe which facets (rushing, receiving, defense, pass_rush) return NCAA and whether a player endpoint gives a birth date; if none does, **age** comes only from a source that has a birthdate (state which) or stays blank.
- Columns "Devy N" are the franchise's devy slot/pick order. Cell colors are only a position hint (green RB, yellow WR, gray QB, pink TE, purple DE/edge, orange LB): **take position from the text**, never the color.
- Some cells are cut off or abbreviated ("Bama", "OSU", "UF", "SC", "Cal", "IND", "Tenn"). Transcribe as written into `source_text`; do not fix by guessing.

## 2. Build (in this order; stop at each gate)

### 2.1 Probe first (live, one call each)
- CFBD: record the real JSON shape of players/search, `roster`, `stats/player/season`, `player/usage`, `player/returning` and `ppa/players/season` to `contracts/cfbd.*.fields`. Check rate limits, the season/week ranges, whether `athlete.id` is stable, and what `height`/`weight`/`year` look like (units, nulls). Age: **CFBD gives no birthdate in most endpoints**; find out what it gives and say so. Do not invent an age.
- PFF: check whether the existing v2 client (`fdb/pff.py`, `api.pff.com`) exposes **college** data (NCAA) for the same key, and what ids it returns. If it does not, say so and run on CFBD alone; PFF college grades become a follow-up.
- Check existing id maps (`player_ids`, DynastyProcess, nflverse `players`, ESPN) for any CFBD/ESPN-college/PFF-NCAA ids before building a mapping table.

### 2.2 Identity (design §3.4; read it first)
- College-only players have no `gsis_id`. Add the surrogate `person_id` the design foresaw **only as far as needed**, and don't hardcode "`gsis_id` is the only key" in new SQL. Join through `player_ids` with its own `source` values (`cfbd`, and `pff_ncaa` if it exists).
- **Never match by name.** Mapping from a screenshot name to a CFBD id is the hard part: use only exact keys (an id already in the maps, or a manual `config/identity_overrides.csv`-style row **with a reason**). A name or school may *reject* a candidate, never select one. Produce a review CSV of every screenshot player with the proposed CFBD id and the evidence, and **hand it to Turon to approve before anything loads against it.** That is the first gate.

### 2.3 Roster seed
`app_devy_roster` (user-entered state; exported before any rebuild per rule 9): `league_id, franchise_id (MFL id), franchise_name, devy_slot, source_text, position, school, person_id (nullable until approved), copies, seen_on`. Put the screenshots' transcription under version control (CSV in `app_state/`), checked for: every franchise listed, counts per franchise equal what's in the picture, positions only QB/RB/WR/TE/DT/DE/EDGE/LB/DB. Franchise ids come from `core_mfl_franchises` for the MFL leagues you already load; for leagues not in `config/my_franchises.toml`, add them (seasons 2025, 2026) and load their franchises, never match a franchise by name.

### 2.4 Loaders (rule 11: each joins `fdb weekly` this phase)
- `cfbd.*` loaders to `core_cfbd_*`: season and weekly player stats, usage, roster (height, weight, class, home), keyed by the source's own athlete id, source field names verbatim. `season_type` on every row; preseason never; a non-final week is never served from cache; a nested-empty payload is empty.
- Scope for a week comes from the existing `completed_weeks()`-style rule for CFB (find or build one with its own owner and tests; **a loader never chooses its own weeks**).
- `pff` college loaders only if §2.1 found them.
- Each loader: field-name check before write, plausibility after, idempotent on re-run (`fdb check`), delete-scope-then-insert in one transaction.

### 2.5 Mart
`mart_devy_*` views: one row per `(season, person)` with owner info per league (`mine`, `owner`, `copies`), the stats below, and renamed fields (rule 3). Rates computed at read time from stored counts, **never averaged**: use `SUM(rate*w)/SUM(w)`. A free-agent view per league: players with no `app_devy_roster` row in that league, ranked by the production score in §3, with the minimum-games filter as a parameter.

### 2.6 Page
New page in the Flask/React app, reading `mart_*` only. League switcher; "My players" first with highlight; "Owned by others" (owner shown); "Free agents to watch" ranked. Columns: name, pos, school, class, height, weight, age (or blank, never invented), position-appropriate stats, games, a trend (last 3 games vs season, computed at read time). Handle the `copies` display for 55757. Verify in the browser at desktop and mobile width.

## 3. Stats (propose in the gate report; Turon may change)
- **QB:** pass att, comp, yards, TD, INT, YPA, comp %, rush att/yards/TD, PPA/EPA per play, sack rate.
- **RB:** carries, rush yards, YPC, rush TD, targets, rec, rec yards, usage/snap share, PPA, (PFF rushing grade/yards after contact if present).
- **WR/TE:** targets, rec, yards, YPR, TD, target share, usage, YPRR if available, PPA, (PFF receiving grade/drop rate if present).
- **IDP:** tackles, solo, TFL, sacks, QB hurries, INT, PD, FF, (PFF defensive/pass-rush grades if present).
- **Production score for free-agent ranking:** a simple, documented points-per-game formula per position from counts, not a black box; show its inputs. Say plainly it is a ranking aid.

## 4. Gate (write to `REBUILD_LOG.md`)
1. **Mapping review**: every screenshot player either mapped by an exact key with evidence, or listed as unmapped. Turon approves the CSV. Not before.
2. Contracts recorded from live responses; loaders idempotent; in `fdb weekly`; a weekly run OK.
3. **Roster counts** match the screenshots per franchise (report differences, none silent).
4. **Spot check** 5 players per position against CFBD's own site/API numbers; every difference explained.
5. Page loads with no console errors; Turon's players highlighted; free-agent list contains no rostered player (test).
6. `fdb rebuild` x2 -> identical hash, 0 network calls. Snapshot the DB first. Tests pass on Windows.

## 5. Rules that bite here
No name matching (the whole point of §2.2); one owner per table; source names verbatim in `core_*`; counts stored, rates at read time; `season_type` on every row, preseason never; never `INSERT OR REPLACE`; non-final never cached; exit 0 is not proof; DB rebuildable from `data/raw/` + code; apps read `mart_*` only; v1 is read-only oracle, never a source. Before any DB write, check for a running `fdb rebuild` (`database\fdb.rebuild.db`). Production is `cmd.exe`: no `&&`. Never print or commit `.env` values.

**Stop at each gate and say plainly it is a clean stopping point.**
