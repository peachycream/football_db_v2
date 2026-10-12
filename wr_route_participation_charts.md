# WR Route Participation Charts — Build Spec

## Goal
Build three charts that extend the "WR Expected vs. Actual Fantasy Points per Route Run" scatter by adding **route participation (RP)**, so that part-time efficiency stops looking like a full-time role.

- **Chart A — Role Map (primary):** x = route participation, y = XFP/RR, with contour lines of constant XFP per team dropback.
- **Chart B — Volume-adjusted XFP vs FP:** x = XFP per team dropback, y = FP per team dropback, with a regression line.
- **Chart C — Original chart, RP-weighted:** x = XFP/RR, y = FP/RR, dot size = RP, RP floor filter.

Default scope: 2026 season, weeks 1 through the latest loaded week, WRs only. Make season, week range, and position configurable through CLI args.

## Project context
- DB: `C:\Users\k-ble\Desktop\football_db\football.db` (SQLite)
- Python 3.13 on Windows (PowerShell): `C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe`
- Put the script in the project's existing scripts/analysis folder. Inspect the repo layout first and follow its conventions.

## Hard rules (team conventions)
1. **Read-only.** No writes to the database. Don't add `--apply` behavior in this script.
2. **Schema probe before any data query.** Print `PRAGMA table_info` for every table used and confirm column names before writing queries. Do not guess column names.
3. **Join names through `players`.** FPD weekly tables have no `name` column, so always use `JOIN players ON players.player_id = t.player_id`.
4. **NAME-ONLY resolver calls.** If any name resolution is needed, don't filter by position or team in the resolver. Those labels are inconsistent and cause roughly 46% false negatives. Apply position filters after resolution, from a trusted source.
5. **Printed output.** Print the probe results, row counts at each step, and the final metrics table to stdout.
6. **Sum before dividing.** Aggregate totals across weeks first, then compute rates. Never average weekly rates.

## Phase 0 — Schema and coverage probe
Print the following:
- Columns of `fpd_receiving_advanced_weekly`. `routes_run` is known; find the expected fantasy points column (XFP) and the actual fantasy points column.
- Whether `fpd_receiving_routes_run_weekly` exists. Note that it has a **Personnel** grain dimension (11/12/21/13/22), so it must be summed across personnel before use or routes will be double- or under-counted.
- Every table that looks team-level (`sqlite_master` names containing `team`, `pbp`, `dropback`, `pass`). Find a source for **team dropbacks per game**.
- Max week loaded for the season, and WR player count per week.
- Where position comes from (`players` table or similar).

If no team-dropback source exists in the database, stop and print a clear message proposing the fallback: nflverse play-by-play, summing `qb_dropback == 1` grouped by `posteam, season, week`. Do not download anything without that being reported first.

## Phase 1 — Assemble the player-week table
One row per player-week:
`player_id, name, team, week, routes_run, xfp, fp, team_dropbacks`

- Team per week should come from the weekly table, not a static roster, so traded players are handled.
- Compute weekly `rp = routes_run / team_dropbacks`.
- **Missed/partial-game handling:** exclude weeks where `routes_run == 0` from both numerator and denominator. Flag weeks with RP < 0.35 as `partial`. Provide a `--drop-partial` flag (default **on**) that removes them so injury exits don't read as a demotion. Print which player-weeks were dropped.

## Phase 2 — Season-to-date metrics
Per player, summing over the included weeks:
- `routes = Σ routes_run`
- `dropbacks = Σ team_dropbacks` (only the weeks included for that player)
- `RP = routes / dropbacks`
- `XFP_RR = Σ xfp / routes`
- `FP_RR = Σ fp / routes`
- `XFP_DB = Σ xfp / dropbacks` (equivalent to XFP_RR × RP)
- `FP_DB = Σ fp / dropbacks`
- `delta_RR = FP_RR − XFP_RR` and `delta_DB = FP_DB − XFP_DB`
- `weeks_included`

Filters (configurable): `--min-routes 50` and `--min-rp 0.0`. Chart C defaults its own floor to RP ≥ 0.60.

Print the final table sorted by `XFP_DB` descending, and save it as a CSV alongside the charts.

## Phase 3 — Charts (matplotlib)
General:
- Label every point with the player name. Use `adjustText` (pip install if missing) to avoid overlaps.
- Title, subtitle with season, weeks, and filters, and a source line ("Data: FantasyPointsData via football.db").
- Dashed median lines on both axes.
- Save PNGs at 200 dpi in an output folder named like `output/route_participation/2026_wk1-N/`.

**Chart A — Role Map**
- x = RP (0–1, formatted as %), y = XFP_RR.
- Draw iso-curves for XFP_DB = x × y at sensible levels (for example 0.20, 0.25, 0.30, 0.35, 0.40), choosing them from the data's quantiles. Label each curve.
- Color points by XFP_DB.
- Light quadrant annotations at the median lines: top-right "Alpha role", top-left "Part-time, earns looks", bottom-right "Full-time, not featured", bottom-left "Fringe".

**Chart B — Volume-adjusted**
- x = XFP_DB, y = FP_DB.
- OLS regression line, dashed gray, mirroring the original chart.
- Color points by `delta_DB`: above the line = overperforming, below = underperforming.

**Chart C — RP-weighted original**
- x = XFP_RR, y = FP_RR, filtered to RP ≥ 0.60 by default.
- Dot size proportional to RP, with a size legend.
- Same regression line and median lines as the original chart.

## Phase 4 — Validation and summary
Print:
- Sanity checks: no RP > 1.05 (flag any player with RP > 1.0, which suggests a dropback or route mismatch), no null XFP, and player count after each filter.
- Spot checks: RP and XFP_DB for Zay Flowers, Jaxon Smith-Njigba, Justin Jefferson, CeeDee Lamb, Mack Hollins, and Puka Nacua.
- Top 10 by `delta_DB` as sell-high candidates, and bottom 10 as buy-low candidates.
- Top 10 by XFP_RR among players with RP < 0.60 as a "role-growth watch" list.

## Optional extension (only if trivial)
If `pff_receiving_weekly` joins cleanly by `player_id` + week, add `--color-by alignment` to Chart A, coloring by season `slot_rate` instead of XFP_DB. Skip it if the join needs name matching.

## Deliverables
- The script, with CLI args: `--season`, `--weeks 1-5`, `--position WR`, `--min-routes`, `--min-rp`, `--drop-partial/--keep-partial`, `--out`.
- Three PNGs, a metrics CSV, and the printed validation summary.
- A short note at the end listing the exact columns and tables used and any assumptions made.
