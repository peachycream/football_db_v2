"""Expected tackles and sacks, v2's own model (REBUILD_DESIGN §6.1, Phase 7b): builder `idp_model.build`.

    mart_idp_expected_tackles_week   per defender-week sums (actual / expected, run / pass)
    mart_idp_tackle_rates            the fitted tackle-probability cells
    mart_idp_expected_sacks_week     per rusher-week sums (wins, sacks, expected sacks)
    mart_idp_sack_rates              sacks per pass-rush win, per position group

EXPECTED TACKLES. For every scrimmage play (pass or run, not a 2-pt try) and every defender
ON THE FIELD for it, P(this defender is credited with a tackle | his position group, the
play kind, the ball carrier's gap and depth). Summed per player-week, that is what an
average player at his position would have been credited with on exactly his snaps.
  * on the field: nflverse participation (2016-2025), FTN all-22 (2026-, joined to the
    nflverse play by nflverse's own FTN mirror). Both list gsis ids: no mapping at all.
  * credit: every pbp tackle slot (solo 1-2, with-assist 1-2, assist 1-4) = one credit,
    v1's settled convention (it reconciles to the vendor's totals; 1.0/0.5 did not).
  * group: the player's PFF position that season (DI->DT, ED->DE), the dashboard's bucket;
    nflverse's play-level label only when PFF has no line for him.
  * cells: kind (run / complete / incomplete / sack) x gap (run: end/tackle/guard/middle;
    completion: outside/middle) x depth (yards gained: <=0, 1-3, 4-6, 7-10, 11-20, 21+).
    Each cell's rate is shrunk toward (group, kind, depth), then (group, kind), by
    SHRINK pseudo-plays, so a thin cell cannot swing a player.
  * fitted on FIT_SEASONS = 2016-2024 ONLY. 2025 is the held-out validation season
    (§6.1 gate), and fixing the window means history never moves when a week is added.
Role is deliberately coarse (position group, not per-play alignment): v1's bake-off found
that a finer role model predicts tackles better by explaining away part of what "tackles
vs expected" exists to measure (residual YoY r 0.457 volume vs 0.421 alignment).

EXPECTED SACKS = pass-rush wins x the group's sacks per win (fitted 2016-2024), per
rusher-week from PFF defense/pass_rush (pff id -> gsis by player_ids).
"""
from collections import defaultdict

from .participation import FTN_FROM

FIT_SEASONS = range(2016, 2025)
SHRINK = 200.0
GROUPS = ("DT", "DE", "LB", "CB", "S")
_LABEL = {"DE": "DE", "DT": "DT", "NT": "DT", "DL": "DT", "IDL": "DT", "OLB": "LB", "ILB": "LB", "MLB": "LB",
          "LB": "LB", "CB": "CB", "SS": "S", "FS": "S", "S": "S", "SAF": "S", "DB": "S"}
TACKLE_COLS = ("solo_tackle_1_player_id", "solo_tackle_2_player_id", "tackle_with_assist_1_player_id",
               "tackle_with_assist_2_player_id", "assist_tackle_1_player_id", "assist_tackle_2_player_id",
               "assist_tackle_3_player_id", "assist_tackle_4_player_id")


def _depth(y):
    if y is None:
        return "none"
    for hi, lab in ((0, "<=0"), (3, "1-3"), (6, "4-6"), (10, "7-10"), (20, "11-20")):
        if y <= hi:
            return lab
    return "21+"


def cell_of(p):
    """(kind, gap, depth) for one pbp play dict."""
    if p["sack"] == 1:
        return "sack", "none", "none"
    if p["rush_attempt"] == 1:
        gap = "middle" if p["run_location"] == "middle" else (p["run_gap"] or "none")
        return "run", gap, _depth(p["yards_gained"])
    if p["complete_pass"] == 1:
        loc = p["pass_location"]
        return "complete", ("middle" if loc == "middle" else "outside" if loc in ("left", "right") else "none"), _depth(p["yards_gained"])
    return "incomplete", "none", "none"


def _groups(conn):
    """(season, gsis) -> group from PFF's season position."""
    return {(s, g): grp for s, g, grp in conn.execute(
        "SELECT season, gsis_id, position_group FROM mart_pff_defense_season WHERE gsis_id IS NOT NULL AND position_group IN "
        "('DT', 'DE', 'LB', 'CB', 'S') ORDER BY season, gsis_id, snaps_total")}


def _on_field(conn, season):
    """(game_id, play_id) -> [(gsis, play-level label), ...]"""
    out = {}
    if season < FTN_FROM:
        for g, p, ids, pos in conn.execute("""SELECT nflverse_game_id, play_id, defense_players, defense_positions
                                               FROM core_participation WHERE season = ?""", (season,)):
            if ids:
                labs = (pos or "").split(";")
                out[(g, int(p))] = [(x, labs[i] if i < len(labs) else None) for i, x in enumerate(ids.split(";")) if x]
        return out, "nflverse"
    sel = ", ".join(f"a.def{i}Id, a.def{i}Pos" for i in range(1, 12))
    for r in conn.execute(f"""SELECT x.nflverse_game_id, x.nflverse_play_id, {sel} FROM core_ftn_all22 a
                              JOIN core_nflverse_ftn_charting x ON x.ftn_play_id = CAST(a.playId AS TEXT)
                              WHERE a.season = ?""", (season,)):
        out[(r[0], int(r[1]))] = [(r[2 + 2 * i], r[3 + 2 * i]) for i in range(11) if r[2 + 2 * i]]
    return out, "ftn"


def _plays(conn, season):
    cols = ("game_id", "play_id", "season_type", "week", "rush_attempt", "sack", "complete_pass", "run_location",
            "run_gap", "pass_location", "yards_gained") + TACKLE_COLS
    for r in conn.execute(f"""SELECT {', '.join(cols)} FROM core_pbp WHERE season = ? AND play_type IN ('pass', 'run')
                              AND two_point_attempt = 0""", (season,)):
        yield dict(zip(cols, r))


def _season_player_plays(conn, season, groups):
    """Yield (season_type, week, gsis, group, cell, credits) per on-field defender-play, plus coverage stats."""
    field, source = _on_field(conn, season)
    stats = {"credits": 0, "credits_on_field": 0, "plays": 0, "plays_with_field": 0}
    rows = []
    for p in _plays(conn, season):
        stats["plays"] += 1
        credited = defaultdict(int)
        for c in TACKLE_COLS:
            if p[c]:
                credited[p[c]] += 1
        stats["credits"] += sum(credited.values())
        players = field.get((p["game_id"], int(p["play_id"])))
        if not players:
            continue
        stats["plays_with_field"] += 1
        cell = cell_of(p)
        for gsis, lab in players:
            grp = groups.get((season, gsis)) or _LABEL.get((lab or "").upper())
            if grp not in GROUPS:
                continue
            n = credited.get(gsis, 0)
            stats["credits_on_field"] += n
            rows.append((p["season_type"], p["week"], gsis, grp, cell, n))
    return rows, source, stats


def fit_rates(counts):
    """counts[(grp, kind, gap, depth)] = [player_plays, credits] -> {cell: rate} with shrinkage."""
    parent, grand = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for (g, k, gap, d), (n, c) in counts.items():
        parent[(g, k, d)][0] += n; parent[(g, k, d)][1] += c
        grand[(g, k)][0] += n; grand[(g, k)][1] += c
    grand_rate = {k: (c / n if n else 0.0) for k, (n, c) in grand.items()}
    parent_rate = {k: (c + SHRINK * grand_rate.get(k[:2], 0.0)) / (n + SHRINK) for k, (n, c) in parent.items()}
    return {k: (c + SHRINK * parent_rate[(k[0], k[1], k[3])]) / (n + SHRINK) for k, (n, c) in counts.items()}, parent_rate, grand_rate


def build(conn) -> dict:
    groups = _groups(conn)
    seasons = sorted({r[0] for r in conn.execute("SELECT DISTINCT season FROM core_pbp")})
    per_season, fails, coverage = {}, [], {}
    counts = defaultdict(lambda: [0, 0])
    for s in seasons:
        rows, source, st = _season_player_plays(conn, s, groups)
        if not rows:
            continue
        per_season[s] = (rows, source)
        coverage[s] = st
        if s in FIT_SEASONS:
            for _, _, _, grp, cell, n in rows:
                k = (grp, *cell)
                counts[k][0] += 1
                counts[k][1] += n
    rates, parent_rate, grand_rate = fit_rates(counts)

    def rate(grp, cell):
        k = (grp, *cell)
        if k in rates:
            return rates[k]
        return parent_rate.get((grp, cell[0], cell[2]), grand_rate.get((grp, cell[0]), 0.0))

    agg = {}
    for s, (rows, source) in per_season.items():
        for st, wk, gsis, grp, cell, n in rows:
            a = agg.setdefault((s, st, wk, gsis), {"grp": defaultdict(int), "rp": 0, "pp": 0, "ar": 0, "ap": 0,
                                                    "er": 0.0, "ep": 0.0, "src": source})
            a["grp"][grp] += 1
            e = rate(grp, cell)
            if cell[0] == "run":
                a["rp"] += 1; a["ar"] += n; a["er"] += e
            else:
                a["pp"] += 1; a["ap"] += n; a["ep"] += e

    # sacks: pass-rush wins x group sacks-per-win (fit seasons only)
    pr = conn.execute("""SELECT x.season, x.season_type, x.week, p.gsis_id,
                                CASE x.position WHEN 'ED' THEN 'DE' WHEN 'DI' THEN 'DT' ELSE x.position END,
                                x.snap_counts_pass_rush, x.pass_rush_opp, x.pass_rush_wins, x.sacks
                         FROM core_pff_pass_rush_week x
                         JOIN player_ids p ON p.source = 'pff' AND p.source_id = CAST(x.player_id AS TEXT)""").fetchall()
    sw = defaultdict(lambda: [0, 0])
    for s, _, _, _, grp, _, _, w, sk in pr:
        if s in FIT_SEASONS:
            sw[grp][0] += w or 0
            sw[grp][1] += sk or 0
    srate = {g: (k / w if w else 0.0) for g, (w, k) in sw.items()}
    sacks = {}
    for s, st, wk, gsis, grp, snaps, opp, w, sk in pr:
        a = sacks.setdefault((s, st, wk, gsis), [grp, 0, 0, 0, 0, 0.0])
        a[1] += snaps or 0; a[2] += opp or 0; a[3] += w or 0; a[4] += sk or 0; a[5] += (w or 0) * srate.get(grp, 0.0)

    conn.execute("BEGIN")
    try:
        for t in ("mart_idp_expected_tackles_week", "mart_idp_tackle_rates", "mart_idp_expected_sacks_week", "mart_idp_sack_rates"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany("INSERT INTO mart_idp_tackle_rates VALUES (?,?,?,?,?,?,?)",
                         [(*k, n, c, rates[k]) for k, (n, c) in sorted(counts.items())])
        conn.executemany("INSERT INTO mart_idp_expected_tackles_week VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(s, st, wk, g, max(a["grp"], key=lambda x: (a["grp"][x], x)), a["rp"], a["pp"], a["ar"], a["ap"],
                           a["er"], a["ep"], a["src"]) for (s, st, wk, g), a in sorted(agg.items())])
        conn.executemany("INSERT INTO mart_idp_sack_rates VALUES (?,?,?,?)",
                         [(g, w, k, srate[g]) for g, (w, k) in sorted(sw.items())])
        conn.executemany("INSERT INTO mart_idp_expected_sacks_week VALUES (?,?,?,?,?,?,?,?,?,?)",
                         [(*k, *v) for k, v in sorted(sacks.items())])
        fails = checks(conn, coverage)
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    n_t = sum(1 for _ in agg)
    return {"failures": fails, "summary": f"{n_t} defender-weeks, {len(sacks)} rusher-weeks, "
                                          f"{len(counts)} tackle cells, sack rates {({g: round(r, 3) for g, r in srate.items() if g in ('DE', 'DT')})}"}


def checks(conn, coverage) -> list[str]:
    fails = []
    for s, st in coverage.items():
        # on-field lists exist for (nearly) every scrimmage play, and hold (nearly) every credited tackler
        if st["plays_with_field"] < 0.97 * st["plays"]:
            fails.append(f"{s}: on-field lists for only {st['plays_with_field']}/{st['plays']} scrimmage plays")
        if st["credits"] and st["credits_on_field"] < 0.95 * st["credits"]:
            fails.append(f"{s}: only {st['credits_on_field']}/{st['credits']} tackle credits went to an on-field defender")
    # the model is unbiased league-wide in every season, in and out of the fit window
    for s, a, e in conn.execute("""SELECT season, SUM(actual_tackles_run + actual_tackles_pass),
                                          SUM(expected_tackles_run + expected_tackles_pass)
                                   FROM mart_idp_expected_tackles_week GROUP BY season"""):
        if e and not 0.90 <= a / e <= 1.10:
            fails.append(f"{s}: actual/expected tackles {a / e:.3f} outside [0.90, 1.10]")
    for s, a, e in conn.execute("""SELECT season, SUM(sacks), SUM(expected_sacks) FROM mart_idp_expected_sacks_week
                                   WHERE position_group IN ('DE', 'DT') GROUP BY season"""):
        if e and not 0.80 <= a / e <= 1.20:
            fails.append(f"{s}: actual/expected sacks (DE+DT) {a / e:.3f} outside [0.80, 1.20]")
    return fails
