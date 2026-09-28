"""Team Offense / Team Defense environment APIs (Phase 6).

Ported from v1 app/offenv_api.py and app/team_def_env.py with the SAME JSON contracts
(the v1 React pages are reused unchanged) and the same metric formulas, percentile /
rank rules (ties share the better rank) and n < 8 small-sample guard. What changed:
the data access. Everything is read from mart_* (fdb/env.py builds the sums; schema
016 has the season-grain PFF views), regular season only, as v1. Record and single-game
info come from the schedule (mart_team_week_opponent), not a cached pbp parquet.
"""
import sqlite3

from flask import Blueprint, jsonify, request

from fdb import config
from fdb.env import DEF_COLS, OFF_COLS

bp = Blueprint("env", __name__)

CORE_SPLITS = ["all", "pass", "rush", "neutral", "neutral_pass", "neutral_rush"]
PERSONNEL_SPLITS = ["p_11", "p_12", "p_21", "p_13", "p_10", "p_22", "p_other"]
OFF_INVERT = {"sec_per_snap", "sack_rate", "pressure_rate_allowed"}
DEF_INVERT = frozenset({"epa_per_play_allowed", "success_rate_allowed", "explosive_rate_allowed",
                        "pass_epa_per_play_allowed", "rush_epa_per_play_allowed", "cpoe_allowed", "comp_pct_allowed",
                        "yards_per_att_allowed", "passer_rating_allowed", "yards_per_coverage_snap_allowed",
                        "deep_target_rate_allowed", "rush_ypc_allowed", "yco_per_att_allowed",
                        "third_down_rate_allowed", "rz_td_rate_allowed", "pts_per_drive_allowed",
                        "neutral_sec_per_snap_faced"})
SCHEME_SUM_COLS = ["man_snaps", "zone_snaps", "cover0_snaps", "cover1_snaps", "cover2_snaps", "cover3_snaps",
                   "cover4_snaps", "cover6_snaps", "other_coverage_snaps", "base_snaps", "nickel_snaps", "dime_snaps",
                   "other_pers_snaps", "blitz_dropbacks", "dropbacks_faced", "lightbox_rush_att", "lightbox_rush_yards",
                   "heavybox_rush_att", "heavybox_rush_yards", "epa_vs_man_sum", "plays_vs_man", "epa_vs_zone_sum",
                   "plays_vs_zone"]
SCHEME_PFF_SUM_COLS = ["pff_man_targets", "pff_man_receptions", "pff_man_yards", "pff_man_coverage_snaps",
                       "pff_zone_targets", "pff_zone_receptions", "pff_zone_yards", "pff_zone_coverage_snaps"]


def _connect():
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _safe_div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _r(v, n):
    return round(v, n) if v is not None else None


def _median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def percentile_of(target, values, invert=False):
    vals = sorted(v for v in values if v is not None)
    if target is None or not vals:
        return None
    return round(100 * (sum(1 for v in vals if v >= target) if invert else sum(1 for v in vals if v <= target)) / len(vals))


def pct_rank_of(target, values, invert=False):
    vals = [v for v in values if v is not None]
    if target is None or not vals:
        return None, None, None
    n = len(vals)
    at = sum(1 for v in vals if v >= target) if invert else sum(1 for v in vals if v <= target)
    better = sum(1 for v in vals if v < target) if invert else sum(1 for v in vals if v > target)
    return round(100 * at / n), better + 1, n


def _metric_obj(value, n, all_vals, invert):
    if n is not None and n < 8:
        return {"v": round(value, 8) if value is not None else None, "pct": None, "n": n}
    pct, rank, n_teams = pct_rank_of(value, all_vals, invert=invert)
    return {"v": round(value, 8) if value is not None else None, "pct": pct, "rank": rank, "n_teams": n_teams}


def _record(con, season, team, lo, hi):
    w = l = t = 0
    for r in con.execute("""SELECT team_score, opp_score FROM mart_team_week_opponent WHERE season = ? AND season_type = 'REG'
                            AND team = ? AND week BETWEEN ? AND ?""", (season, team, lo, hi)):
        if r["team_score"] is None or r["opp_score"] is None:
            continue
        if r["team_score"] > r["opp_score"]:
            w += 1
        elif r["team_score"] < r["opp_score"]:
            l += 1
        else:
            t += 1
    return None if w + l + t == 0 else f"{w}-{l}" + (f"-{t}" if t else "")


def _game_info(con, season, team, week):
    g = con.execute("""SELECT opponent, is_home, team_score, opp_score FROM mart_team_week_opponent
                       WHERE season = ? AND season_type = 'REG' AND team = ? AND week = ?""", (season, team, week)).fetchone()
    if g is None:
        return None
    ts, os_ = g["team_score"], g["opp_score"]
    result = None if ts is None or os_ is None else ("W" if ts > os_ else "L" if ts < os_ else "T")
    return {"opponent": g["opponent"], "home_away": "home" if g["is_home"] else "away",
            "team_score": ts, "opp_score": os_, "result": result}


def _max_week(con, table, season):
    r = con.execute(f"SELECT MAX(week) FROM {table} WHERE season = ? AND season_type = 'REG'", (season,)).fetchone()
    return r[0] if r and r[0] else 18


# ================================================================== offense ===
def off_metrics(p):
    p = {c: (p.get(c) or 0) for c in OFF_COLS}
    m = {"epa_per_play": _safe_div(p["epa_sum"], p["plays"]), "success_rate": _safe_div(p["success_sum"], p["plays"]),
         "cpoe": _safe_div(p["cpoe_sum"], p["cpoe_n"]), "adot": _safe_div(p["air_yards_sum"], p["pass_att"]),
         "explosive_rate": _safe_div(p["explosive_rush"] + p["explosive_pass"], p["plays"]),
         "pa_rate": _safe_div(p["pa_plays"], p["dropbacks"]), "pa_epa": _safe_div(p["pa_epa_sum"], p["pa_plays"]),
         "screen_rate": _safe_div(p["screen_plays"], p["dropbacks"]), "sack_rate": _safe_div(p["sacks"], p["dropbacks"]),
         "sec_per_snap": _safe_div(p["pace_sec_sum"], p["pace_snap_n"]),
         "no_huddle_rate": _safe_div(p["no_huddle_plays"], p["plays"]),
         "pts_per_drive": _safe_div(p["points"], p["drives"]), "drive_success": _safe_div(p["drive_scores"], p["drives"]),
         "third_down_rate": _safe_div(p["third_down_conv"], p["third_down_att"]),
         "early_down_pass_rate": _safe_div(p["early_down_pass"], p["early_down_plays"]),
         "rz_td_rate": _safe_div(p["rz_td"], p["rz_trips"])}
    share, xp = _safe_div(p["dropbacks"], p["plays"]), _safe_div(p["xpass_sum"], p["xpass_n"])
    m["proe"] = share - xp if share is not None and xp is not None else None
    m["pass_rate"], m["n"] = share, p["plays"]
    return m


def _off_sums(con, season, lo, hi):
    sel = ",".join(f"SUM({c}) AS {c}" for c in OFF_COLS)
    out = {}
    for r in con.execute(f"""SELECT team, split, {sel} FROM mart_team_off_env_week WHERE season = ? AND season_type = 'REG'
                             AND week BETWEEN ? AND ? GROUP BY team, split""", (season, lo, hi)):
        d = dict(r)
        t, s = d.pop("team"), d.pop("split")
        out.setdefault(t, {})[s] = off_metrics(d)
    return out


def _off_obj(metrics, key, all_sums, split):
    return _metric_obj(metrics.get(key), metrics.get("n"), [tm.get(split, {}).get(key) for tm in all_sums.values()],
                       key in OFF_INVERT)


@bp.route("/api/team-offense-env")
def team_offense_env():
    season = request.args.get("season", type=int)
    team = (request.args.get("team") or "").strip().upper()
    side = (request.args.get("side") or "off").strip()
    if not season or not team:
        return jsonify({"error": "season and team are required"}), 400
    con = _connect()
    try:
        lo = request.args.get("week_start", type=int) or 1
        last = _max_week(con, "mart_team_off_env_week", season)
        hi = min(request.args.get("week_end", type=int) or last, last)   # the bundle asks for 1-18 mid-season
        all_sums = _off_sums(con, season, lo, hi)
        if team not in all_sums:
            return jsonify({"error": f"no data for team={team} season={season} weeks {lo}-{hi}"}), 404
        tm = all_sums[team]
        games = {}
        for r in con.execute("""SELECT team, COUNT(*) FROM mart_team_off_env_week WHERE season = ? AND season_type = 'REG'
                                AND week BETWEEN ? AND ? AND split = 'all' AND plays > 0 GROUP BY team""", (season, lo, hi)):
            games[r[0]] = r[1]
        ppg = {t: _safe_div(s.get("all", {}).get("n"), games.get(t)) for t, s in all_sums.items()}
        p_pct, p_rank, p_n = pct_rank_of(ppg.get(team), ppg.values())
        header = {"record": _record(con, season, team, lo, hi),
                  "epa_play": _off_obj(tm.get("all", {}), "epa_per_play", all_sums, "all"),
                  "proe": _off_obj(tm.get("all", {}), "proe", all_sums, "all"),
                  "pace": _off_obj(tm.get("neutral", {}), "sec_per_snap", all_sums, "neutral"),
                  "plays_per_game": {"v": _r(ppg.get(team), 2), "pct": p_pct, "rank": p_rank, "n_teams": p_n},
                  "game": _game_info(con, season, team, lo) if lo == hi else None}
        keys = ["epa_per_play", "success_rate", "cpoe", "explosive_rate", "adot", "proe", "sack_rate", "pa_rate", "pa_epa",
                "screen_rate", "sec_per_snap", "no_huddle_rate", "pts_per_drive", "drive_success", "third_down_rate",
                "early_down_pass_rate", "rz_td_rate"]
        splits = {}
        for sp in CORE_SPLITS:
            m = tm.get(sp, {})
            splits[sp] = {"n": m.get("n", 0), **{k: _off_obj(m, k, all_sums, sp) for k in keys}}
        trend = {k: [] for k in ("epa_play", "proe", "success_rate", "pace", "explosive_rate")}
        median = {k: [] for k in trend}
        weeks_present, weeks_missing = [], []
        for w in range(lo, hi + 1):
            wk = _off_sums(con, season, w, w)
            am, nm = wk.get(team, {}).get("all", {}), wk.get(team, {}).get("neutral", {})
            if am.get("n"):
                for k, src in (("epa_play", "epa_per_play"), ("proe", "proe"), ("success_rate", "success_rate"),
                               ("explosive_rate", "explosive_rate")):
                    trend[k].append([w, _r(am[src], 8)])
            if nm.get("sec_per_snap") is not None:
                trend["pace"].append([w, round(nm["sec_per_snap"], 2)])
            alls = [s.get("all", {}) for s in wk.values()]
            neus = [s.get("neutral", {}) for s in wk.values()]
            for k, src in (("epa_play", "epa_per_play"), ("proe", "proe"), ("success_rate", "success_rate"),
                           ("explosive_rate", "explosive_rate")):
                median[k].append([w, _r(_median(m.get(src) for m in alls), 8)])
            median["pace"].append([w, _r(_median(m.get("sec_per_snap") for m in neus), 2)])
            has = any((wk.get(team, {}).get(s, {}).get("n") or 0) > 0 for s in PERSONNEL_SPLITS)
            (weeks_present if has else weeks_missing).append(w)
        pb = {r["team"]: _safe_div(r["grade_x_snaps"], r["snaps"]) for r in
              con.execute("SELECT team, grade_x_snaps, snaps FROM mart_team_pass_block_season WHERE season = ?", (season,))}
        pr = {r["team"]: (100.0 * r["p"] / r["d"] if r["d"] else None) for r in con.execute(
              """SELECT team, SUM(pressures) p, SUM(dropbacks) d FROM mart_team_pressure_allowed_week
                 WHERE season = ? AND season_type = 'REG' GROUP BY team""", (season,))}
        pr_pct, pr_rank, pr_n = pct_rank_of(pr.get(team), [pr.get(t) for t in all_sums], invert=True)
        pb_pct, pb_rank, pb_n = pct_rank_of(pb.get(team), [pb.get(t) for t in all_sums])
        context = {"pass_block_grade": {"v": _r(pb.get(team), 8), "pct": pb_pct, "rank": pb_rank, "n_teams": pb_n},
                   "pressure_rate_allowed": {"v": _r(pr.get(team), 8), "pct": pr_pct, "rank": pr_rank, "n_teams": pr_n}}
        league_table = [{"team": t, "epa_play": _r(s.get("all", {}).get("epa_per_play"), 8),
                         "proe": _r(s.get("all", {}).get("proe"), 8),
                         "pace": _r(s.get("neutral", {}).get("sec_per_snap"), 2),
                         "success_rate": _r(s.get("all", {}).get("success_rate"), 8)} for t, s in all_sums.items()]
        league_table.sort(key=lambda d: (d["epa_play"] is None, -(d["epa_play"] or 0)))
        total = sum((tm.get(s, {}).get("n") or 0) for s in PERSONNEL_SPLITS)
        personnel = []
        if total:
            for sp in PERSONNEL_SPLITS:
                m = tm.get(sp, {})
                n = m.get("n") or 0
                if not n:
                    continue
                shares = []
                for other in all_sums.values():
                    t_tot = sum((other.get(s, {}).get("n") or 0) for s in PERSONNEL_SPLITS)
                    shares.append((other.get(sp, {}).get("n") or 0) / t_tot if t_tot else None)
                personnel.append({"grp": sp[2:], "snap_share": round(n / total, 4), "epa_play": _r(m.get("epa_per_play"), 8),
                                  "pass_rate": _r(m.get("pass_rate"), 4),
                                  "pct_usage": percentile_of(n / total, shares)})
            personnel.sort(key=lambda d: -d["snap_share"])
        tgt = {}
        for r in con.execute("""SELECT team, bucket, SUM(targets) t FROM mart_team_targets_week WHERE season = ? AND season_type = 'REG'
                                AND week BETWEEN ? AND ? GROUP BY team, bucket""", (season, lo, hi)):
            d = tgt.setdefault(r["team"], {"RB": 0, "WR": 0, "TE": 0, "total": 0})
            d["total"] += r["t"] or 0
            if r["bucket"] in d:
                d[r["bucket"]] += r["t"] or 0
        rates = {t: ({k: d[k] / d["total"] for k in ("RB", "WR", "TE")} if d["total"] else dict.fromkeys(("RB", "WR", "TE")))
                 for t, d in tgt.items()}
        by_pos = {}
        for pos in ("RB", "WR", "TE"):
            v = rates.get(team, {}).get(pos)
            pct, rank, n = pct_rank_of(v, [d.get(pos) for d in rates.values()])
            by_pos[pos] = {"v": _r(v, 4), "pct": pct, "rank": rank, "n_teams": n}
        return jsonify({"team": team, "season": season, "weeks": [lo, hi], "side": side, "header": header,
                        "splits": splits, "target_rate_by_position": by_pos, "personnel": personnel,
                        "personnel_coverage": {"weeks_present": weeks_present, "weeks_missing": weeks_missing},
                        "trend": trend, "trend_league_median": median, "context": context, "league_table": league_table})
    finally:
        con.close()


# ================================================================== defense ===
def _passer_rating(att, comp, yards, td, ints):
    if not att:
        return None
    a = max(0, min(((comp / att) - 0.3) * 5, 2.375))
    b = max(0, min(((yards / att) - 3) * 0.25, 2.375))
    c = max(0, min((td / att) * 20, 2.375))
    d = max(0, min(2.375 - ((ints / att) * 25), 2.375))
    return ((a + b + c + d) / 6) * 100


def def_metrics(row):
    p = {c: row.get(c) for c in DEF_COLS}   # NULL preserved: v1's hard-won rule (a missing stat never ranks first)
    z = lambda v: v or 0
    m = {"epa_per_play_allowed": _safe_div(p["epa_sum_allowed"], p["def_plays"]),
         "success_rate_allowed": _safe_div(p["success_ct_allowed"], p["def_plays"]),
         "explosive_rate_allowed": _safe_div(p["explosive_ct_allowed"], p["def_plays"]),
         "pass_epa_per_play_allowed": _safe_div(p["pass_epa_sum_allowed"], p["dropbacks_faced"]),
         "rush_epa_per_play_allowed": _safe_div(p["rush_epa_sum_allowed"], p["rush_att_faced"]),
         "early_epa_per_play": _safe_div(p["early_epa_sum"], p["early_plays"]),
         "late_epa_per_play": _safe_div(p["late_epa_sum"], p["late_plays"]),
         "cpoe_allowed": _safe_div(p["cpoe_x_dropbacks"], p["att_allowed"]),
         "comp_pct_allowed": _safe_div(p["comp_allowed"], p["att_allowed"]),
         "yards_per_att_allowed": _safe_div(p["cov_yards_allowed"], p["att_allowed"]),
         "passer_rating_allowed": _passer_rating(z(p["att_allowed"]), z(p["comp_allowed"]), z(p["cov_yards_allowed"]),
                                                 z(p["cov_td_allowed"]), z(p["cov_int"])),
         "yards_per_coverage_snap_allowed": _safe_div(p["cov_yards_allowed"], p["dropbacks_faced"]),
         "deep_target_rate_allowed": _safe_div(p["deep_targets_allowed"], p["att_allowed"]),
         "pressure_rate": _safe_div(p["pressures"], p["pass_rush_snaps"]),
         "sack_rate_allowed": _safe_div(p["sacks"], p["dropbacks_faced"]),
         "hurry_rate": _safe_div(p["hurries"], p["pass_rush_snaps"]),
         "qb_hit_rate": _safe_div(p["qb_hits"], p["pass_rush_snaps"]),
         "pressure_rate_4man_ftn": _safe_div(p["pressures_4man_ftn"], p["pass_rush_plays_4man_ftn"]),
         "rush_ypc_allowed": _safe_div(p["rush_yards_allowed"], p["rush_att_faced"]),
         "yco_per_att_allowed": _safe_div(p["yco_allowed_sum"], p["rush_att_faced"]),
         "stuff_rate": _safe_div(p["stuffs"], p["rush_att_faced"]),
         "third_down_rate_allowed": _safe_div(p["third_down_conv_allowed"], p["third_down_faced"]),
         "rz_td_rate_allowed": _safe_div(p["rz_td_allowed"], p["rz_trips_faced"]),
         "three_and_out_rate_forced": _safe_div(p["three_and_out_forced"], p["drives_faced"]),
         "havoc_rate": _safe_div(p["havoc_plays"], p["def_plays"]),
         "pts_per_drive_allowed": _safe_div(p["points_allowed"], p["drives_faced"]),
         "neutral_sec_per_snap_faced": _safe_div(p["neutral_seconds_faced"], p["neutral_plays_faced"]),
         "run_def_grade": _safe_div(p["run_def_grade_x_snaps"], p["tackle_grade_snaps"]),
         "tackle_grade": _safe_div(p["tackle_grade_x_snaps"], p["tackle_grade_snaps"])}
    share, xp = _safe_div(p["dropbacks_faced"], p["def_plays"]), _safe_div(p["proe_x_plays_faced"], p["def_plays"])
    m["proe_faced"] = share - xp if share is not None and xp is not None else None
    m["blitz_rate"], m["n"] = None, z(p["def_plays"])
    return m


def _def_sums(con, season, lo, hi):
    sel = ",".join(f"SUM({c}) AS {c}" for c in DEF_COLS)
    out = {}
    for r in con.execute(f"""SELECT team, {sel} FROM mart_team_def_env_week WHERE season = ? AND season_type = 'REG'
                             AND week BETWEEN ? AND ? GROUP BY team""", (season, lo, hi)):
        d = dict(r)
        out[d.pop("team")] = def_metrics(d)
    return out


def _def_obj(m, key, all_sums):
    return _metric_obj(m.get(key), m.get("n"), [t.get(key) for t in all_sums.values()], key in DEF_INVERT)


def _scheme(con, team, season, lo, hi):
    through = con.execute("SELECT MAX(season) FROM mart_team_def_scheme_week WHERE source = 'ftn_participation'").fetchone()[0]
    if not through or season > through:
        return None
    part_sel = ",".join(f"SUM({c}) AS {c}" for c in SCHEME_SUM_COLS)
    part = con.execute(f"""SELECT {part_sel} FROM mart_team_def_scheme_week WHERE team = ? AND season = ? AND season_type = 'REG'
                           AND week BETWEEN ? AND ? AND source = 'ftn_participation'""", (team, season, lo, hi)).fetchone()
    pff_sel = ",".join(f"SUM({c}) AS {c}" for c in SCHEME_PFF_SUM_COLS)
    pff = con.execute(f"""SELECT {pff_sel} FROM mart_team_def_scheme_week WHERE team = ? AND season = ? AND season_type = 'REG'
                          AND week BETWEEN ? AND ? AND source = 'pff'""", (team, season, lo, hi)).fetchone()
    part = dict(part) if part and part["man_snaps"] is not None else None
    pff = dict(pff) if pff and pff["pff_man_targets"] is not None else None
    if part is None and pff is None:
        return None
    out = {"through_season": through}
    if part:
        g = lambda c: part.get(c) or 0
        cov = sum(g(c) for c in ("cover0_snaps", "cover1_snaps", "cover2_snaps", "cover3_snaps", "cover4_snaps",
                                 "cover6_snaps", "other_coverage_snaps"))
        pers = sum(g(c) for c in ("base_snaps", "nickel_snaps", "dime_snaps", "other_pers_snaps"))
        mz = g("man_snaps") + g("zone_snaps")
        out["man_zone"] = {"man_rate": _r(_safe_div(part["man_snaps"], mz), 4), "zone_rate": _r(_safe_div(part["zone_snaps"], mz), 4),
                           "epa_per_play_vs_man": _r(_safe_div(part["epa_vs_man_sum"], part["plays_vs_man"]), 8),
                           "epa_per_play_vs_zone": _r(_safe_div(part["epa_vs_zone_sum"], part["plays_vs_zone"]), 8)}
        out["coverage_shell"] = {f"{k}_rate": _r(_safe_div(part[f"{k}_snaps"], cov), 4)
                                 for k in ("cover0", "cover1", "cover2", "cover3", "cover4", "cover6")}
        out["coverage_shell"]["other_rate"] = _r(_safe_div(part["other_coverage_snaps"], cov), 4)
        out["personnel"] = {f"{k}_rate": _r(_safe_div(part[f"{k}_snaps"], pers), 4) for k in ("base", "nickel", "dime")}
        out["personnel"]["other_rate"] = _r(_safe_div(part["other_pers_snaps"], pers), 4)
        out["blitz_rate"] = _r(_safe_div(part["blitz_dropbacks"], part["dropbacks_faced"]), 4)
        out["box_counts"] = {"lightbox_ypc": _r(_safe_div(part["lightbox_rush_yards"], part["lightbox_rush_att"]), 3),
                             "heavybox_ypc": _r(_safe_div(part["heavybox_rush_yards"], part["heavybox_rush_att"]), 3)}
    if pff:
        out["pff_coverage"] = {"man_catch_rate": _r(_safe_div(pff["pff_man_receptions"], pff["pff_man_targets"]), 4),
                               "man_yards_per_target": _r(_safe_div(pff["pff_man_yards"], pff["pff_man_targets"]), 3),
                               "zone_catch_rate": _r(_safe_div(pff["pff_zone_receptions"], pff["pff_zone_targets"]), 4),
                               "zone_yards_per_target": _r(_safe_div(pff["pff_zone_yards"], pff["pff_zone_targets"]), 3)}
    return out


@bp.route("/api/team-defense-env")
def team_defense_env():
    season = request.args.get("season", type=int)
    team = (request.args.get("team") or "").strip().upper()
    if not season or not team:
        return jsonify({"error": "season and team are required"}), 400
    con = _connect()
    try:
        lo = request.args.get("week_start", type=int) or 1
        last = _max_week(con, "mart_team_def_env_week", season)
        hi = min(request.args.get("week_end", type=int) or last, last)   # the bundle asks for 1-18 mid-season
        all_sums = _def_sums(con, season, lo, hi)
        if team not in all_sums:
            return jsonify({"error": f"no data for team={team} season={season} weeks {lo}-{hi}"}), 404
        m = all_sums[team]
        games = {r[0]: r[1] for r in con.execute("""SELECT team, COUNT(*) FROM mart_team_def_env_week WHERE season = ?
                   AND season_type = 'REG' AND week BETWEEN ? AND ? AND def_plays > 0 GROUP BY team""", (season, lo, hi))}
        ppg = {t: _safe_div(tm.get("n"), games.get(t)) for t, tm in all_sums.items()}
        p_pct, p_rank, p_n = pct_rank_of(ppg.get(team), ppg.values(), invert=True)
        o = lambda k: _def_obj(m, k, all_sums)
        header = {"record_allowed": _record(con, season, team, lo, hi), "epa_play_allowed": o("epa_per_play_allowed"),
                  "havoc_rate": o("havoc_rate"),
                  "plays_faced_per_game": {"v": _r(ppg.get(team), 2), "pct": p_pct, "rank": p_rank, "n_teams": p_n},
                  "game": _game_info(con, season, team, lo) if lo == hi else None}
        grades_raw = {r["team"]: {"def_grade": _safe_div(r["def_grade_x_snaps"], r["snaps"]),
                                  "pass_rush_grade": _safe_div(r["pass_rush_grade_x_snaps"], r["snaps"]),
                                  "coverage_grade": _safe_div(r["coverage_grade_x_snaps"], r["snaps"])}
                      for r in con.execute("SELECT * FROM mart_team_def_grades_season WHERE season = ?", (season,))}
        grades = {}
        for k in ("def_grade", "pass_rush_grade", "coverage_grade"):
            v = grades_raw.get(team, {}).get(k)
            pct, rank, n = pct_rank_of(v, [g.get(k) for g in grades_raw.values()])
            grades[k] = {"v": _r(v, 8), "pct": pct, "rank": rank, "n_teams": n}
        grades["run_def_grade"], grades["tackle_grade"] = o("run_def_grade"), o("tackle_grade")
        tkeys = ["epa_per_play_allowed", "success_rate_allowed", "havoc_rate", "pts_per_drive_allowed"]
        trend, median = {k: [] for k in tkeys}, {k: [] for k in tkeys}
        for w in range(lo, hi + 1):
            wk = _def_sums(con, season, w, w)
            wm = wk.get(team, {})
            if wm.get("n"):
                for k in tkeys:
                    trend[k].append([w, _r(wm.get(k), 8)])
            for k in tkeys:
                median[k].append([w, _r(_median(t.get(k) for t in wk.values()), 8)])
        league_table = [{"team": t, "epa_play_allowed": _r(tm.get("epa_per_play_allowed"), 8),
                         "success_rate_allowed": _r(tm.get("success_rate_allowed"), 8), "havoc_rate": _r(tm.get("havoc_rate"), 8),
                         "pts_per_drive_allowed": _r(tm.get("pts_per_drive_allowed"), 4)} for t, tm in all_sums.items()]
        league_table.sort(key=lambda d: (d["epa_play_allowed"] is None, d["epa_play_allowed"] or 0))
        return jsonify({
            "team": team, "season": season, "weeks": [lo, hi], "header": header,
            "volume_efficiency": {"n": m.get("n", 0), **{k: o(k) for k in (
                "epa_per_play_allowed", "success_rate_allowed", "explosive_rate_allowed", "pass_epa_per_play_allowed",
                "rush_epa_per_play_allowed", "early_epa_per_play", "late_epa_per_play", "proe_faced",
                "neutral_sec_per_snap_faced", "pts_per_drive_allowed")}},
            "pass_rush": {k: o(k) for k in ("pressure_rate", "sack_rate_allowed", "hurry_rate", "qb_hit_rate",
                                            "pressure_rate_4man_ftn")},
            "coverage": {k: o(k) for k in ("comp_pct_allowed", "yards_per_att_allowed", "passer_rating_allowed",
                                           "cpoe_allowed", "yards_per_coverage_snap_allowed", "deep_target_rate_allowed")},
            "run_defense": {k: o(k) for k in ("rush_ypc_allowed", "yco_per_att_allowed", "stuff_rate")},
            "situational": {k: o(k) for k in ("third_down_rate_allowed", "rz_td_rate_allowed", "three_and_out_rate_forced")},
            "havoc": {"havoc_rate": o("havoc_rate")}, "grades": grades,
            "scheme": _scheme(con, team, season, lo, hi), "trend": trend, "trend_league_median": median,
            "league_table": league_table})
    finally:
        con.close()


@bp.route("/api/team-defense-env/gameday")
def team_defense_env_gameday():
    season = request.args.get("season", type=int)
    team = (request.args.get("team") or "").strip().upper()
    if not season or not team:
        return jsonify({"error": "season and team are required"}), 400
    con = _connect()
    try:
        r = con.execute("SELECT MAX(week) FROM mart_team_def_env_week WHERE season = ? AND season_type = 'REG' AND team = ?",
                        (season, team)).fetchone()
        wk = r[0] if r else None
        if wk is None:
            return jsonify({"error": f"no data for team={team} season={season}"}), 404
        all_sums = _def_sums(con, season, wk, wk)
        m = all_sums.get(team, {})
        o = lambda k: _def_obj(m, k, all_sums)
        return jsonify({"team": team, "season": season, "week": wk,
                        "volume_efficiency": {k: o(k) for k in ("epa_per_play_allowed", "success_rate_allowed")},
                        "pass_rush": {k: o(k) for k in ("pressure_rate", "sack_rate_allowed")},
                        "coverage": {k: o(k) for k in ("comp_pct_allowed", "passer_rating_allowed")},
                        "run_defense": {k: o(k) for k in ("rush_ypc_allowed", "stuff_rate")}})
    finally:
        con.close()
