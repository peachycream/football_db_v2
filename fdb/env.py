"""Team environment marts (REBUILD_DESIGN §6, Phase 6): builder `env.build`.

    mart_team_off_env_week    one row per (season, season_type, week, team, split)  - SUMS only
    mart_team_def_env_week    one row per (season, season_type, week, team)         - SUMS only
    mart_team_def_scheme_week one row per (season, season_type, week, team, source) - SUMS only

Formulas mirror v1's proven builders EXACTLY (agent_offense_env_weekly_v1.py,
build_def_env_weekly.py) - the rate logic is theirs, so rankings are comparable -
with v2's sources and three deliberate corrections, each named where it applies:
  * personnel comes from mart_participation_personnel (backs = RB + FB). v1's regex
    read only the 'RB' token, so from 2023 (when nflverse split FB out) every
    fullback play lost its back: 21 personnel read as 11.
  * 2026 personnel exists (FTN via the seam mart, joined to pbp by nflverse's FTN charting
    mirror, which carries both play ids); v1 had none. 2026 4-man pressure does NOT: the
    mirror has n_pass_rushers but no pressure flag, so it stays NULL (never 0).
  * PFF inputs are v2's PFF tables, whose season lines are REG+POST only (v1's
    per-team grade tables were partly REG-only, partly all-inclusive).
Rates are computed at read time in the apps (SUM(num)/SUM(den); never AVG of a rate).
Every season_type is built; the apps read REG, as v1 did.
"""
from collections import defaultdict

NAMED = {"11", "12", "21", "13", "10", "22"}
CORE_SPLITS = ["all", "pass", "rush", "neutral", "neutral_pass", "neutral_rush"]
PERSONNEL_SPLITS = [f"p_{c}" for c in ("11", "12", "21", "13", "10", "22")] + ["p_other"]

OFF_COLS = ["plays", "dropbacks", "pass_att", "rush_att", "sacks", "epa_sum", "success_sum", "cpoe_sum", "cpoe_n",
            "xpass_sum", "xpass_n", "air_yards_sum", "explosive_rush", "explosive_pass", "pa_plays", "pa_epa_sum",
            "screen_plays", "screen_epa_sum", "pace_sec_sum", "pace_snap_n", "no_huddle_plays", "drives", "drive_scores",
            "points", "third_down_att", "third_down_conv", "early_down_plays", "early_down_pass", "rz_trips", "rz_td"]
DEF_COLS = ["def_plays", "dropbacks_faced", "rush_att_faced", "neutral_plays_faced", "neutral_seconds_faced",
            "points_allowed", "drives_faced", "epa_sum_allowed", "success_ct_allowed", "explosive_ct_allowed",
            "pass_epa_sum_allowed", "rush_epa_sum_allowed", "early_epa_sum", "early_plays", "late_epa_sum", "late_plays",
            "cpoe_x_dropbacks", "comp_allowed", "att_allowed", "cov_yards_allowed", "cov_td_allowed", "cov_int",
            "air_yards_allowed_sum", "yac_allowed_sum", "deep_targets_allowed", "pass_rush_snaps", "pressures", "sacks",
            "hurries", "qb_hits", "rush_yards_allowed", "yco_allowed_sum", "stuffs", "third_down_faced",
            "third_down_conv_allowed", "rz_trips_faced", "rz_td_allowed", "three_and_out_forced", "proe_x_plays_faced",
            "tfl", "forced_fumbles", "pass_breakups", "havoc_plays", "run_def_grade_x_snaps", "tackle_grade_x_snaps",
            "tackle_grade_snaps", "pressures_4man_ftn", "pass_rush_plays_4man_ftn"]
SCHEME_COLS = ["man_snaps", "zone_snaps", "cover0_snaps", "cover1_snaps", "cover2_snaps", "cover3_snaps",
               "cover4_snaps", "cover6_snaps", "other_coverage_snaps", "base_snaps", "nickel_snaps", "dime_snaps",
               "other_pers_snaps", "blitz_dropbacks", "dropbacks_faced", "lightbox_rush_att", "lightbox_rush_yards",
               "heavybox_rush_att", "heavybox_rush_yards", "epa_vs_man_sum", "plays_vs_man", "epa_vs_zone_sum",
               "plays_vs_zone", "pff_man_targets", "pff_man_receptions", "pff_man_yards", "pff_man_coverage_snaps",
               "pff_zone_targets", "pff_zone_receptions", "pff_zone_yards", "pff_zone_coverage_snaps"]

PBP_COLS = ["game_id", "play_id", "season", "season_type", "week", "posteam", "defteam", "play_type", "qb_kneel",
            "qb_spike", "wp", "half_seconds_remaining", "qb_dropback", "cpoe", "sack", "epa", "success", "xpass",
            "air_yards", "yards_gained", "complete_pass", "no_huddle", "drive", "game_seconds_remaining",
            "fixed_drive_result", "yardline_100", "rush_touchdown", "pass_touchdown", "extra_point_result",
            "two_point_conv_result", "field_goal_result", "down", "third_down_converted", "drive_play_count",
            "interception", "yards_after_catch", "tackled_for_loss", "fumble_forced", "pass_defense_1_player_id",
            "pass_defense_2_player_id"]


def _n(v):
    return v or 0


def _pace(rows):
    """Snap-to-snap deltas within (game_id, drive), clipped [5, 45] (v1 pace_for_rows)."""
    by = defaultdict(list)
    for r in rows:
        if r["drive"] is not None and r["game_seconds_remaining"] is not None:
            by[(r["game_id"], r["drive"])].append(r["game_seconds_remaining"])
    tot, n = 0.0, 0
    for secs in by.values():
        secs.sort(reverse=True)
        for a, b in zip(secs, secs[1:]):
            tot += min(45.0, max(5.0, a - b))
            n += 1
    return tot, n


def _drive_stats(broad):
    """v1 drive_stats_for_team / drive_stats_for_defteam, on one team-week's plays."""
    first, minyl, count = {}, {}, {}
    for r in broad:                           # pbp order: the first row of a drive wins
        d = r["drive"]
        if d is None:
            continue
        if d not in first:
            first[d], count[d] = r["fixed_drive_result"], r["drive_play_count"]
        if r["yardline_100"] is not None:
            minyl[d] = min(minyl.get(d, 1e9), r["yardline_100"])
    drives = len(first)
    scores = sum(1 for v in first.values() if v in ("Touchdown", "Field goal"))
    rz = [d for d in first if minyl.get(d, 1e9) <= 20]
    rz_td = sum(1 for d in rz if first[d] == "Touchdown")
    three_out = sum(1 for d in first if (count[d] is not None and count[d] <= 3) and first[d] == "Punt")
    td = sum(1 for r in broad if r["rush_touchdown"] == 1 or r["pass_touchdown"] == 1)
    xp = sum(1 for r in broad if r["extra_point_result"] == "good")
    two = sum(1 for r in broad if r["two_point_conv_result"] == "success")
    fg = sum(1 for r in broad if r["field_goal_result"] == "made")
    return {"drives": drives, "drive_scores": scores, "points": td * 6 + xp + two * 2 + fg * 3,
            "rz_trips": len(rz), "rz_td": rz_td, "three_and_out": three_out}


def _is_pass(r):
    return r["qb_dropback"] == 1


def _is_rush(r):
    return r["play_type"] == "run" and r["qb_dropback"] == 0


def _load_season(conn, season):
    cols = ", ".join(f"b.{c}" for c in PBP_COLS)
    rows = [dict(r) for r in conn.execute(f"""SELECT {cols}, ftn.is_play_action, ftn.is_screen_pass,
                                                   per.personnel AS personnel
                                            FROM core_pbp b
                                            LEFT JOIN core_nflverse_ftn_charting ftn
                                              ON ftn.nflverse_game_id = b.game_id AND ftn.nflverse_play_id = b.play_id
                                            LEFT JOIN mart_participation_personnel per
                                              ON per.source = 'nflverse' AND per.game_key = b.game_id
                                             AND per.play_key = CAST(b.play_id AS TEXT)
                                            WHERE b.season = ? ORDER BY b.game_id, b.play_id""", (season,))]
    # FTN seasons (>= FTN_FROM): personnel keyed by FTN pid -> nflverse play via nflverse's FTN mirror
    ftn = {(g, int(p)): pers for g, p, pers in conn.execute("""
             SELECT c.nflverse_game_id, c.nflverse_play_id, per.personnel FROM mart_participation_personnel per
             JOIN core_nflverse_ftn_charting c ON c.ftn_play_id = per.play_key
             WHERE per.source = 'ftn' AND per.season = ?""", (season,))}
    if ftn:
        for r in rows:
            if r["personnel"] is None:
                r["personnel"] = ftn.get((r["game_id"], r["play_id"]))
    for r in rows:
        r["pa"] = 1 if r["is_play_action"] == "TRUE" else 0
        r["screen"] = 1 if r["is_screen_pass"] == "TRUE" else 0
        p = r["personnel"]
        r["pbucket"] = None if p is None else (p if p in NAMED else "other")
    return rows


def _off_row(rows, split, broad):
    out = dict.fromkeys(OFF_COLS, 0)
    out["epa_sum"] = out["cpoe_sum"] = out["xpass_sum"] = out["air_yards_sum"] = 0.0
    out["pa_epa_sum"] = out["screen_epa_sum"] = out["pace_sec_sum"] = 0.0
    for r in rows:
        out["plays"] += 1
        out["dropbacks"] += r["qb_dropback"] == 1
        out["rush_att"] += _is_rush(r)
        out["sacks"] += _n(r["sack"])
        out["epa_sum"] += _n(r["epa"])
        out["success_sum"] += _n(r["success"])
        if r["cpoe"] is not None:
            out["pass_att"] += 1
            out["cpoe_sum"] += r["cpoe"]
            out["cpoe_n"] += 1
        if r["xpass"] is not None:
            out["xpass_sum"] += r["xpass"]
            out["xpass_n"] += 1
        if r["air_yards"] is not None:
            out["air_yards_sum"] += r["air_yards"]
        out["explosive_rush"] += r["play_type"] == "run" and _n(r["yards_gained"]) >= 10
        out["explosive_pass"] += r["complete_pass"] == 1 and _n(r["yards_gained"]) >= 20
        if r["pa"]:
            out["pa_plays"] += 1
            out["pa_epa_sum"] += _n(r["epa"])
        if r["screen"]:
            out["screen_plays"] += 1
            out["screen_epa_sum"] += _n(r["epa"])
    if split == "neutral":
        out["pace_sec_sum"], out["pace_snap_n"] = _pace(rows)
        out["no_huddle_plays"] = sum(_n(r["no_huddle"]) for r in rows)
    if split == "all":
        d = _drive_stats(broad)
        out.update(drives=d["drives"], drive_scores=d["drive_scores"], points=d["points"], rz_trips=d["rz_trips"],
                   rz_td=d["rz_td"])
        third = [r for r in rows if r["down"] == 3]
        early = [r for r in rows if r["down"] in (1, 2)]
        out.update(third_down_att=len(third), third_down_conv=sum(r["third_down_converted"] == 1 for r in third),
                   early_down_plays=len(early), early_down_pass=sum(r["qb_dropback"] == 1 for r in early))
    return out


def _split(rows, split):
    if split == "all":
        return rows
    if split == "pass":
        return [r for r in rows if _is_pass(r)]
    if split == "rush":
        return [r for r in rows if _is_rush(r)]
    if split == "neutral":
        return [r for r in rows if r["neutral"]]
    if split == "neutral_pass":
        return [r for r in rows if r["neutral"] and _is_pass(r)]
    if split == "neutral_rush":
        return [r for r in rows if r["neutral"] and _is_rush(r)]
    return [r for r in rows if r["pbucket"] == split[2:]]


def _def_row(rows, broad):
    o = {c: 0 for c in DEF_COLS}
    for c in ("neutral_seconds_faced", "epa_sum_allowed", "pass_epa_sum_allowed", "rush_epa_sum_allowed",
              "early_epa_sum", "late_epa_sum", "cpoe_x_dropbacks", "air_yards_allowed_sum", "yac_allowed_sum",
              "proe_x_plays_faced"):
        o[c] = 0.0
    neutral = []
    for r in rows:
        o["def_plays"] += 1
        p, ru = _is_pass(r), _is_rush(r)
        o["dropbacks_faced"] += p
        o["rush_att_faced"] += ru
        if r["neutral"]:
            neutral.append(r)
        e = _n(r["epa"])
        o["epa_sum_allowed"] += e
        o["success_ct_allowed"] += _n(r["success"])
        o["explosive_ct_allowed"] += (ru and _n(r["yards_gained"]) >= 10) + (r["complete_pass"] == 1 and _n(r["yards_gained"]) >= 20)
        if p:
            o["pass_epa_sum_allowed"] += e
        if ru:
            o["rush_epa_sum_allowed"] += e
            o["rush_yards_allowed"] += _n(r["yards_gained"])
            o["stuffs"] += _n(r["yards_gained"]) <= 0
        if r["down"] in (1, 2):
            o["early_epa_sum"] += e
            o["early_plays"] += 1
        if r["down"] in (3, 4):
            o["late_epa_sum"] += e
            o["late_plays"] += 1
        if r["cpoe"] is not None:
            o["cpoe_x_dropbacks"] += r["cpoe"]
            o["att_allowed"] += 1
            o["air_yards_allowed_sum"] += _n(r["air_yards"])
            o["deep_targets_allowed"] += _n(r["air_yards"]) >= 20
        if r["complete_pass"] == 1:
            o["comp_allowed"] += 1
            o["cov_yards_allowed"] += _n(r["yards_gained"])
            o["yac_allowed_sum"] += _n(r["yards_after_catch"])
        o["cov_td_allowed"] += _n(r["pass_touchdown"])
        o["cov_int"] += _n(r["interception"])
        if r["down"] == 3:
            o["third_down_faced"] += 1
            o["third_down_conv_allowed"] += _n(r["third_down_converted"])
        o["proe_x_plays_faced"] += _n(r["xpass"])
        o["tfl"] += _n(r["tackled_for_loss"])
        o["forced_fumbles"] += _n(r["fumble_forced"])
        o["pass_breakups"] += (r["pass_defense_1_player_id"] is not None) + (r["pass_defense_2_player_id"] is not None)
        o["sacks"] += _n(r["sack"])
    o["havoc_plays"] = o["tfl"] + o["forced_fumbles"] + o["pass_breakups"] + o["cov_int"]
    o["neutral_plays_faced"] = len(neutral)
    o["neutral_seconds_faced"] = _pace(neutral)[0]
    d = _drive_stats(broad)
    o.update(drives_faced=d["drives"], points_allowed=d["points"], rz_trips_faced=d["rz_trips"],
             rz_td_allowed=d["rz_td"], three_and_out_forced=d["three_and_out"])
    for c in ("pass_rush_snaps", "pressures", "hurries", "qb_hits", "yco_allowed_sum", "run_def_grade_x_snaps",
              "tackle_grade_x_snaps", "tackle_grade_snaps", "pressures_4man_ftn", "pass_rush_plays_4man_ftn"):
        o[c] = None   # PFF/FTN inputs, filled from their own sources (None = no source, never 0)
    return o


def _pff_def(conn, season):
    """(season_type, week, team) -> PFF pass-rush sums and snap-weighted grade numerators."""
    out = {}
    for r in conn.execute("""SELECT x.season_type, x.week, a.team, SUM(x.snap_counts_pass_rush) prs, SUM(x.total_pressures) pr,
                                    SUM(x.hurries) hu, SUM(x.hits) hi,
                                    SUM(CASE WHEN x.snap_counts_defense > 0 THEN x.grades_tackle * x.snap_counts_defense END) tg,
                                    SUM(CASE WHEN x.snap_counts_defense > 0 THEN x.grades_run_defense * x.snap_counts_defense END) rg,
                                    SUM(CASE WHEN x.snap_counts_defense > 0 THEN x.snap_counts_defense END) sn
                             FROM core_pff_defense_week x
                             JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
                             WHERE x.season = ? GROUP BY 1, 2, 3""", (season,)):
        out[(r["season_type"], r["week"], r["team"])] = r
    return out


def _yco(conn, season):
    """rush yards after contact ALLOWED: PFF rushing is keyed to the rusher's team; the
    defense is its schedule opponent that week (exact, via mart_team_week_opponent)."""
    return {(r[0], r[1], r[2]): r[3] for r in conn.execute("""
        SELECT x.season_type, x.week, o.opponent, SUM(x.yards_after_contact) FROM core_pff_rushing_week x
        JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
        JOIN mart_team_week_opponent o ON o.season = x.season AND o.season_type = x.season_type AND o.week = x.week
         AND o.team = a.team
        WHERE x.season = ? GROUP BY 1, 2, 3""", (season,))}


def _ftn_4man(conn, season):
    """4-man pressure: nflverse participation (number_of_pass_rushers, was_pressure) on
    pass plays, defteam from pbp (v1 load_ftn_4man_pressure). None for 2026 (no source)."""
    out = defaultdict(lambda: [0, 0])
    for r in conn.execute("""SELECT b.season_type, b.week, a.team, x.number_of_pass_rushers n, x.was_pressure p
                             FROM core_participation x
                             JOIN core_pbp b ON b.game_id = x.nflverse_game_id AND b.play_id = x.play_id
                             JOIN team_aliases a ON a.abbr = b.defteam AND b.season BETWEEN a.season_from AND a.season_to
                             WHERE x.season = ? AND b.play_type = 'pass' AND x.number_of_pass_rushers IS NOT NULL
                               AND x.was_pressure IS NOT NULL""", (season,)):
        if r["n"] <= 4:
            k = (r["season_type"], r["week"], r["team"])
            out[k][0] += 1 if str(r["p"]).upper() in ("1", "TRUE") else 0
            out[k][1] += 1
    return out


def _def_personnel_bucket(raw):
    """v1 _personnel_bucket_def: 'X DB' (2016-22) or CB+FS+SS(+S) (2023+) -> base/nickel/dime/other."""
    import re
    if not isinstance(raw, str):
        return None
    m = re.search(r"(\d+)\s*DB\b", raw)
    if m:
        db = int(m.group(1))
    else:
        found, db = False, 0
        for tok in ("CB", "FS", "SS", "S"):
            sm = re.findall(rf"(\d+)\s*{tok}\b", raw)
            if sm:
                found = True
                db += sum(int(x) for x in sm)
        if not found:
            return None
    return {4: "base", 5: "nickel", 6: "dime"}.get(db, "other")


def _scheme(conn, season, rows_by_key):
    """Participation (nflverse, complete seasons) + PFF coverage scheme, per defteam-week."""
    out = {}
    COVER = {"COVER_0": "cover0_snaps", "COVER_1": "cover1_snaps", "COVER_2": "cover2_snaps",
             "COVER_3": "cover3_snaps", "COVER_4": "cover4_snaps", "COVER_6": "cover6_snaps"}
    OTHER = {"2_MAN", "BLOWN", "COMBO", "COVER_9", "PREVENT"}
    part = conn.execute("""SELECT b.season_type, b.week, a.team, b.play_type, b.epa, b.yards_gained,
                                  x.defense_man_zone_type mz, x.defense_coverage_type cov, x.defense_personnel pers,
                                  x.defenders_in_box box, x.number_of_pass_rushers npr
                           FROM core_participation x
                           JOIN core_pbp b ON b.game_id = x.nflverse_game_id AND b.play_id = x.play_id
                           JOIN team_aliases a ON a.abbr = b.defteam AND b.season BETWEEN a.season_from AND a.season_to
                           WHERE x.season = ? AND b.play_type IN ('pass', 'run')""", (season,)).fetchall()
    for r in part:
        k = (r["season_type"], r["week"], r["team"], "ftn_participation")
        o = out.setdefault(k, {c: 0 for c in SCHEME_COLS[:23]} | {"epa_vs_man_sum": 0.0, "epa_vs_zone_sum": 0.0})
        mz = (r["mz"] or "").lower()
        if "man" in mz:
            o["man_snaps"] += 1
            o["epa_vs_man_sum"] += _n(r["epa"])
            o["plays_vs_man"] += 1
        if "zone" in mz:
            o["zone_snaps"] += 1
            o["epa_vs_zone_sum"] += _n(r["epa"])
            o["plays_vs_zone"] += 1
        if r["cov"] in COVER:
            o[COVER[r["cov"]]] += 1
        elif r["cov"] in OTHER:
            o["other_coverage_snaps"] += 1
        b = _def_personnel_bucket(r["pers"])
        if b:
            o[f"{b}_snaps" if b != "other" else "other_pers_snaps"] += 1
        if r["play_type"] == "pass":
            o["dropbacks_faced"] += 1
            if r["npr"] is not None and r["npr"] >= 5:
                o["blitz_dropbacks"] += 1
        if r["play_type"] == "run" and r["box"] is not None:
            if r["box"] <= 6:
                o["lightbox_rush_att"] += 1
                o["lightbox_rush_yards"] += _n(r["yards_gained"])
            elif r["box"] >= 8:
                o["heavybox_rush_att"] += 1
                o["heavybox_rush_yards"] += _n(r["yards_gained"])
    for r in conn.execute("""SELECT x.season_type, x.week, a.team, SUM(x.man_targets) mt, SUM(x.man_receptions) mr,
                                    SUM(x.man_yards) my, SUM(x.man_snap_counts_coverage) mc, SUM(x.zone_targets) zt,
                                    SUM(x.zone_receptions) zr, SUM(x.zone_yards) zy, SUM(x.zone_snap_counts_coverage) zc
                             FROM core_pff_coverage_scheme_week x
                             JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
                             WHERE x.season = ? GROUP BY 1, 2, 3""", (season,)):
        out[(r["season_type"], r["week"], r["team"], "pff")] = {
            "pff_man_targets": r["mt"], "pff_man_receptions": r["mr"], "pff_man_yards": r["my"],
            "pff_man_coverage_snaps": r["mc"], "pff_zone_targets": r["zt"], "pff_zone_receptions": r["zr"],
            "pff_zone_yards": r["zy"], "pff_zone_coverage_snaps": r["zc"]}
    return out


def build_season(conn, season):
    rows = _load_season(conn, season)
    alias = {r[0]: r[1] for r in conn.execute("SELECT abbr, team FROM team_aliases WHERE ? BETWEEN season_from AND season_to",
                                               (season,))}
    broad = defaultdict(list)
    off = defaultdict(list)
    dfn = defaultdict(list)
    dbroad = defaultdict(list)
    for r in rows:
        if r["play_type"] is None:
            continue
        pt, dt = alias.get(r["posteam"]), alias.get(r["defteam"])
        key = (r["season_type"], r["week"])
        if pt:
            broad[key + (pt,)].append(r)
        if dt:
            dbroad[key + (dt,)].append(r)
        if r["qb_kneel"] == 0 and r["qb_spike"] == 0 and r["play_type"] in ("pass", "run"):
            r["neutral"] = (r["wp"] is not None and 0.20 <= r["wp"] <= 0.80 and _n(r["half_seconds_remaining"]) > 120)
            if pt:
                off[key + (pt,)].append(r)
            if dt:
                dfn[key + (dt,)].append(r)
    off_rows = []
    for k in sorted(set(off) | set(broad)):
        team_off = off.get(k, [])
        splits = CORE_SPLITS + (PERSONNEL_SPLITS if any(r["pbucket"] for r in team_off) else [])
        for sp in splits:
            off_rows.append((season, k[0], k[1], k[2], sp, _off_row(_split(team_off, sp), sp, broad.get(k, []))))
    pff, yco, ftn4 = _pff_def(conn, season), _yco(conn, season), _ftn_4man(conn, season)
    def_rows = []
    for k in sorted(set(dfn) | set(dbroad)):
        o = _def_row(dfn.get(k, []), dbroad.get(k, []))
        p = pff.get(k)
        if p:
            o.update(pass_rush_snaps=p["prs"], pressures=p["pr"], hurries=p["hu"], qb_hits=p["hi"],
                     tackle_grade_x_snaps=p["tg"], run_def_grade_x_snaps=p["rg"], tackle_grade_snaps=p["sn"])
        if k in yco:
            o["yco_allowed_sum"] = yco[k]
        if k in ftn4:
            o["pressures_4man_ftn"], o["pass_rush_plays_4man_ftn"] = ftn4[k]
        def_rows.append((season,) + k + (o,))
    scheme = _scheme(conn, season, None)
    return off_rows, def_rows, scheme


def build(conn) -> dict:
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM core_pbp ORDER BY season")]
    conn.execute("BEGIN")
    try:
        for t in ("mart_team_off_env_week", "mart_team_def_env_week", "mart_team_def_scheme_week"):
            conn.execute(f"DELETE FROM {t}")
        n_off = n_def = n_sch = 0
        for s in seasons:
            off_rows, def_rows, scheme = build_season(conn, s)
            conn.executemany(f"INSERT INTO mart_team_off_env_week (season, season_type, week, team, split, {', '.join(OFF_COLS)}) "
                             f"VALUES ({', '.join('?' * (5 + len(OFF_COLS)))})",
                             [(a, b, c, d, e, *[o[x] for x in OFF_COLS]) for a, b, c, d, e, o in off_rows])
            conn.executemany(f"INSERT INTO mart_team_def_env_week (season, season_type, week, team, {', '.join(DEF_COLS)}) "
                             f"VALUES ({', '.join('?' * (4 + len(DEF_COLS)))})",
                             [(a, b, c, d, *[o[x] for x in DEF_COLS]) for a, b, c, d, o in def_rows])
            conn.executemany(f"INSERT INTO mart_team_def_scheme_week (season, season_type, week, team, source, {', '.join(SCHEME_COLS)}) "
                             f"VALUES ({', '.join('?' * (5 + len(SCHEME_COLS)))})",
                             [(s, *k, *[o.get(x) for x in SCHEME_COLS]) for k, o in scheme.items()])
            n_off, n_def, n_sch = n_off + len(off_rows), n_def + len(def_rows), n_sch + len(scheme)
        fails = []
        # checks: league mean EPA/play within [-0.15, 0.15] for every full REG week (v1 gate_check)
        for s, w, m in conn.execute("""SELECT season, week, SUM(epa_sum) / SUM(plays) FROM mart_team_off_env_week
                                       WHERE split = 'all' AND season_type = 'REG' GROUP BY 1, 2"""):
            if not -0.15 <= m <= 0.15:
                fails.append(f"{s} wk{w}: league EPA/play {m:.3f} outside [-0.15, 0.15]")
        bad = conn.execute("SELECT COUNT(*) FROM mart_team_off_env_week WHERE success_sum > plays").fetchone()[0]
        if bad:
            fails.append(f"{bad} rows with success > plays")
        if fails:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"failures": fails, "summary": f"{n_off} offense split-rows, {n_def} defense rows, {n_sch} scheme rows"}
