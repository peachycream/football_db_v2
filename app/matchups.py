"""MATCHUPS (Phase 6): which defenses allow the most fantasy points to each position.

Ported from v1 app/matchups.py with the SAME JSON contract (the v1 React page is
reused unchanged). What changed and why:
  * Reads mart_player_allowed_week (PLAYER-GAME rows) instead of v1's team-week raw
    sums: MFL scores per player-game with bonuses ("5/300"), which a team-week sum
    cannot reproduce. Points are computed here, never stored (hard rule 4).
  * League scoring = fdb.scoring: every rule naming the position applies, additively,
    with increments truncated - 98.6-99.4% of offensive player-games equal MFL's own
    reported points in all six leagues (2025). v1 used one coefficient per event from
    a rules table that had collapsed MFL's multi-row rules (PY '*0.05' lost to
    '10/500' -> 0.02/yd); league-mode numbers therefore differ from v1 BY DESIGN.
  * IDP calibration (OI-8) is the same method (median MFL-reported / predicted, newest
    season with >= 30 players), with the exact chain MFL id -> gsis -> PFF id.
  * Sleeper scoring is deferred (REBUILD_DESIGN §10.3): Sleeper leagues are not offered.
  * Kickers are available: PFF field goals are loaded (v1's meta said "unavailable").
  * REG only, as v1: the week range is regular season.
Per-game = SUM(points) / SUM(games). Never AVG() of a stored rate.
"""
import sqlite3
from collections import defaultdict

from flask import Blueprint, jsonify, request

from fdb import config, scoring

bp = Blueprint("matchups", __name__)

OFF_GROUPS = ("QB", "RB", "WR", "TE")
DEF_GROUPS = ("DT", "DE", "LB", "CB", "S")
PK_GROUPS = ("PK",)
ALL_GROUPS = OFF_GROUPS + DEF_GROUPS + PK_GROUPS

OFF_STAT_COLS = ["pass_attempts", "completions", "pass_yards", "pass_tds", "interceptions", "sacks", "sack_yards",
                 "carries", "rush_yards", "rush_tds", "targets", "receptions", "rec_yards", "rec_tds", "fumbles",
                 "fumbles_lost", "fumbles_total", "passing_2pt", "rushing_2pt", "receiving_2pt", "passing_first_downs",
                 "rushing_first_downs", "receiving_first_downs", "special_teams_tds", "kr_yards", "pr_yards",
                 "def_tackles", "def_assists", "def_forced_fumbles"]
DEF_STAT_COLS = ["def_tackles", "def_assists", "def_tfl", "def_sacks", "def_qb_hits", "def_pass_breakups",
                 "def_batted_passes", "def_interceptions", "def_int_tds", "def_forced_fumbles", "def_fumble_recoveries",
                 "def_fr_tds", "def_safeties", "def_tds", "def_stops", "def_pressures", "def_snaps", "def_cov_targets",
                 "def_cov_receptions", "def_cov_yards"]
PK_STAT_COLS = ["fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50p", "fg_att_0_19",
                "fg_att_20_29", "fg_att_30_39", "fg_att_40_49", "fg_att_50p", "fg_made_total", "fg_att_total",
                "pat_made", "pat_att"]
PK_UNSCORED_COLS = {"fg_att_0_19", "fg_att_20_29", "fg_att_30_39", "fg_att_40_49", "fg_att_50p", "fg_made_total",
                    "fg_att_total", "pat_att"}
DESCRIPTIVE = {
    "QB": ["completions", "pass_attempts", "pass_yards", "pass_tds", "interceptions", "sacks"],
    "RB": ["carries", "rush_yards", "rush_tds", "receptions", "rec_yards"],
    "WR": ["targets", "receptions", "rec_yards", "rec_tds"],
    "TE": ["targets", "receptions", "rec_yards", "rec_tds"],
    "DT": ["def_tackles", "def_assists", "def_sacks", "def_tfl", "def_qb_hits", "def_pressures", "def_snaps"],
    "DE": ["def_tackles", "def_assists", "def_sacks", "def_tfl", "def_qb_hits", "def_pressures", "def_snaps"],
    "LB": ["def_tackles", "def_assists", "def_sacks", "def_tfl", "def_pass_breakups", "def_snaps"],
    "CB": ["def_tackles", "def_assists", "def_pass_breakups", "def_interceptions", "def_cov_targets",
           "def_cov_receptions", "def_cov_yards"],
    "S": ["def_tackles", "def_assists", "def_pass_breakups", "def_interceptions", "def_cov_targets", "def_cov_yards"],
    "PK": ["fg_made_total", "fg_att_total", "fg_made_40_49", "fg_made_50p", "pat_made"],
}
_CAL = {}


def _db():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def side_of(g):
    return "st" if g in PK_GROUPS else ("off" if g in OFF_GROUPS else "def")


def _cols(g):
    s = side_of(g)
    return PK_STAT_COLS if s == "st" else OFF_STAT_COLS if s == "off" else DEF_STAT_COLS


def _leagues(conn):
    from fdb import leagues
    names = {r["league_id"]: r["name"] for r in conn.execute("SELECT league_id, name FROM mart_mfl_leagues")}
    return [(lg.league_id, names.get(lg.league_id, lg.name)) for lg in leagues.for_platform("mfl")
            if conn.execute("SELECT 1 FROM mart_mfl_rules WHERE league_id = ? LIMIT 1", (lg.league_id,)).fetchone()]


def build_scorer(conn, scoring_id, g, calibrate=True):
    """-> (score_fn, meta). score_fn(player-game row) -> points."""
    cols = [c for c in _cols(g) if c not in PK_UNSCORED_COLS]
    if side_of(g) == "off" and (not scoring_id or scoring_id == "ppr"):
        # Generic PPR's IDP half is for IDP groups only: an offensive player's
        # special-teams tackles score under an MFL league (its rules name QB/RB/WR/TE),
        # never under the generic baseline.
        cols = [c for c in cols if not c.startswith("def_")]
    rules, rule_season, league_name, factor, cal_season = None, None, None, 1.0, None
    notes = []
    if scoring_id and scoring_id != "ppr":
        num = str(scoring_id).split(":")[1] if str(scoring_id).startswith("mfl:") else str(scoring_id)
        if str(scoring_id).startswith("sleeper:"):
            raise ValueError("Sleeper scoring is deferred in v2 (REBUILD_DESIGN §10.3); pick an MFL league or PPR")
        known = dict(_leagues(conn))
        if num not in known:
            raise ValueError(f"unknown league '{scoring_id}' -- registered leagues are {', '.join(known)}")
        all_rules, rule_season = scoring.catch_all_rules(conn, num)
        league_name = known[num]
        rules = {} if g == "PK" else all_rules.get(g, {})
        if calibrate and side_of(g) == "def":
            if num not in _CAL:
                _CAL[num] = scoring.idp_calibration(conn, num, all_rules)
            factors, seasons = _CAL[num]
            factor, cal_season = factors.get(g, 1.0), seasons.get(g)
        notes.append(f"MFL rules for {num} ({rule_season}) applied per player-game: every rule naming {g} applies, "
                     "additively; increments truncated (fdb/scoring.py)")
        if factor != 1.0:
            notes.append(f"league-scored {g} multiplied by empirical calibration {factor:.3f} (median MFL-reported / "
                         f"predicted, {cal_season}); ?calibrate=0 to disable")
    else:
        notes.append("generic scoring: offense is standard full-PPR; the IDP half is a house baseline, not a standard")
    pk_default = g in PK_GROUPS and (rules is None or not any(e in rules for e in ("FG", "EP", "PAT")))
    sc = scoring.Scorer(cols, rules=rules if rules is not None else None,
                        ppr=scoring.PPR_POINTS if rules is None else None, pk_default=pk_default)
    if g in PK_GROUPS:
        notes.append("PK IS SCORED BY A HOUSE DEFAULT, NOT BY ANY LEAGUE RULE (no registered league scores kicking): "
                     "FG 0-39=3 / 40-49=4 / 50+=5 / PAT=1, misses 0. Use for relative ranking.")
    unscored = [{"component": c, "reason": scoring.UNSCORABLE[c]} for c in _cols(g) if c in scoring.UNSCORABLE]
    unscored += [{"component": c, "reason": f"no matching event code in this league's rules for position {g}"}
                 for c in _cols(g) if c not in scoring.UNSCORABLE and c not in PK_UNSCORED_COLS and c not in sc.scored
                 and rules is not None]

    def score(row, _f=factor):
        return sc(row) * _f

    meta = {"mode": "default_pk" if pk_default else ("ppr" if rules is None else "league"),
            "league_id": scoring_id if rules is not None else None, "league_name": league_name,
            "rule_source": f"mfl:{num}:{rule_season}" if rules is not None else None,
            "scored_components": sorted(sc.scored), "unscored_components": unscored,
            "idp_calibration": round(factor, 3) if rules is not None and side_of(g) == "def" and calibrate else None,
            "mapping_notes": notes}
    return score, meta


def _games(conn, season, lo, hi):
    """(team, week) REG games played in the range: the per-game denominator."""
    return {(r["team"], r["week"]) for r in conn.execute(
        """SELECT team, week FROM mart_team_week_opponent WHERE season = ? AND season_type = 'REG'
           AND week BETWEEN ? AND ? AND result IS NOT NULL""", (season, lo, hi))}


def _rankings(conn, season, g, lo, hi, score):
    games = _games(conn, season, lo, hi)
    fp, raw, players = defaultdict(float), defaultdict(lambda: defaultdict(float)), defaultdict(set)
    desc = DESCRIPTIVE[g]
    for r in conn.execute("""SELECT * FROM mart_player_allowed_week WHERE season = ? AND season_type = 'REG'
                             AND position_group = ? AND week BETWEEN ? AND ?""", (season, g, lo, hi)):
        t = r["allowing_team"]
        fp[t] += score(r)
        for c in desc:
            raw[t][c] += r[c] or 0
        players[(t, r["week"])].add(r["player_key"])
    per_team_games = defaultdict(int)
    for t, _ in games:
        per_team_games[t] += 1
    out, tot_fp, tot_g = [], 0.0, 0
    for t, gp in per_team_games.items():
        total = fp.get(t, 0.0)
        tot_fp += total
        tot_g += gp
        n_players = sum(len(v) for (tt, _), v in players.items() if tt == t)
        out.append({"team": t, "games": gp, "players_per_game": round(n_players / gp, 2),
                    "fp_allowed_total": round(total, 2), "fp_allowed_per_game": round(total / gp, 2),
                    "_exact": total / gp,
                    "descriptive_per_game": {c: round(raw[t][c] / gp, 2) for c in desc}})
    avg = tot_fp / tot_g if tot_g else 0.0
    for o in out:
        o["matchup_multiplier"] = round(o.pop("_exact") / avg, 3) if avg else 1.0
    out.sort(key=lambda x: x["fp_allowed_per_game"], reverse=True)
    for i, o in enumerate(out, 1):
        o["rank"] = i
    return out, round(avg, 2)


def _week_opponents(conn, season, week):
    return {r["team"]: r["opponent"] for r in conn.execute(
        "SELECT team, opponent FROM mart_team_week_opponent WHERE season = ? AND season_type = 'REG' AND week = ?",
        (season, week))}


def _players_facing(conn, season, week, g, rank_by_team, score, limit, max_per_team=3, min_recent_games=2):
    """v1 semantics: the player's last-3-games FP/G x the opponent's matchup multiplier,
    at most `max_per_team` per offense, games-played floor unless top-quartile."""
    opp = _week_opponents(conn, season, week)
    if not opp:
        return []
    lo, hi = max(1, week - 3), week - 1
    agg = {}
    for r in conn.execute("""SELECT * FROM mart_player_allowed_week WHERE season = ? AND season_type = 'REG'
                             AND position_group = ? AND week BETWEEN ? AND ?""", (season, g, lo, hi)):
        a = agg.setdefault(r["player_key"], {"fp": 0.0, "weeks": set(), "teams": set(), "raw": defaultdict(float),
                                             "name": r["name"], "team": r["team"], "gsis": r["gsis_id"]})
        a["fp"] += score(r)
        a["weeks"].add(r["week"])
        a["teams"].add(r["team"])
        a["team"] = max(a["teams"])
        for c in _cols(g):
            if c not in scoring.UNSCORABLE and c not in PK_UNSCORED_COLS:
                a["raw"][c] += r[c] or 0
    names = {r["gsis_id"]: r["display_name"] for r in conn.execute("SELECT gsis_id, display_name FROM players")}
    out = []
    for key, a in agg.items():
        o = opp.get(a["team"])
        rk = rank_by_team.get(o) if o else None
        if rk is None:
            continue
        gp = len(a["weeks"])
        rec_pg = round(a["fp"] / gp, 2) if gp else 0.0
        mult = rk.get("matchup_multiplier", 1.0)
        out.append({"player_id": a["gsis"] or key, "name": names.get(a["gsis"]) or a["name"] or key,
                    "position": g, "team": a["team"], "opponent": o, "opponent_rank": rk["rank"],
                    "opponent_fp_allowed_per_game": rk["fp_allowed_per_game"], "matchup_multiplier": mult,
                    "recent_games": gp, "recent_raw": dict(a["raw"]), "recent_fp_per_game": rec_pg,
                    "projected_fp_per_game": round(rec_pg * mult, 2), "collision": len(a["teams"]) > 1})
    pool = sorted((p["recent_fp_per_game"] for p in out if p["recent_games"] > 0), reverse=True)
    hot = pool[max(0, len(pool) // 4 - 1)] if pool else 0.0
    need = min(min_recent_games, max(0, (week - 1) - max(1, week - 3) + 1))
    kept = [p for p in out if p["recent_games"] >= need or p["recent_fp_per_game"] >= hot]
    kept.sort(key=lambda x: (-x["projected_fp_per_game"], -x["recent_fp_per_game"]))
    final, per_team = [], defaultdict(int)
    for p in kept:
        if max_per_team and per_team[p["team"]] >= max_per_team:
            continue
        per_team[p["team"]] += 1
        final.append(p)
        if len(final) >= limit:
            break
    return final


def _default_week(conn, season):
    """The week to open on: the next week after the last completed REG week (v1
    season_ctx 'next_week'); a closed season clamps to its last REG week."""
    from fdb import schedule
    done = [w for t, w in schedule.completed_weeks(conn, season) if t == "REG"]
    last = conn.execute("SELECT MAX(week) FROM core_schedule WHERE season = ? AND season_type = 'REG'", (season,)).fetchone()[0]
    return min((max(done) + 1) if done else 1, last or 18)


@bp.route("/api/matchups/meta")
def meta():
    conn = _db()
    try:
        seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM mart_player_allowed_week ORDER BY season DESC")]
        weeks = [r[0] for r in conn.execute("SELECT DISTINCT week FROM core_schedule WHERE season_type = 'REG' ORDER BY week")]
        teams = [r[0] for r in conn.execute("SELECT team FROM teams ORDER BY team")]
        leagues = [{"id": num, "name": name, "off_only": False} for num, name in _leagues(conn)]
        season = seasons[0] if seasons else None
        return jsonify({
            "seasons": seasons, "weeks": weeks,
            "latest": {"season": season, "week": _default_week(conn, season) if season else None},
            "teams": teams,
            "positions": {"off": list(OFF_GROUPS), "def": list(DEF_GROUPS), "st": list(PK_GROUPS)},
            "scoring_options": [{"id": "ppr", "name": "Generic PPR", "off_only": False}] + leagues,
            "notes": ["Kickers use PFF field-goal data scored by a house default (no league scores kicking).",
                      "Sleeper scoring is deferred in v2 (REBUILD_DESIGN §10.3), so Sleeper leagues are not offered."],
        })
    finally:
        conn.close()


@bp.route("/api/matchups/rankings")
def rankings():
    season = request.args.get("season", type=int)
    week = request.args.get("week", type=int)
    position = (request.args.get("position") or "").upper()
    scoring_id = request.args.get("scoring") or "ppr"
    side = request.args.get("side")
    limit = request.args.get("limit", default=10, type=int)
    max_per_team = request.args.get("max_per_team", default=3, type=int)
    min_recent_games = request.args.get("min_recent_games", default=2, type=int)
    calibrate = request.args.get("calibrate", default="1") not in ("0", "false", "no")
    if not season:
        return jsonify({"error": "season is required"}), 400
    if position not in ALL_GROUPS:
        return jsonify({"error": f"position must be one of {', '.join(ALL_GROUPS)}"}), 400
    if side and side != side_of(position):
        return jsonify({"error": f"position {position} is side '{side_of(position)}', not '{side}'"}), 400
    conn = _db()
    try:
        try:
            score, smeta = build_scorer(conn, scoring_id, position, calibrate)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        lo, hi = (1, week - 1) if week else (1, 18)
        if week and hi < lo:
            return jsonify({"season": season, "week": week, "position": position, "side": side_of(position),
                            "scoring": smeta, "week_range": None, "rankings": [], "players": [],
                            "warnings": ["week 1 has no prior-week data to rank defenses by"]})
        ranks, league_avg = _rankings(conn, season, position, lo, hi, score)
        players, warnings = [], []
        if week:
            players = _players_facing(conn, season, week, position, {r["team"]: r for r in ranks}, score, limit,
                                      max_per_team, min_recent_games)
            if not players:
                warnings.append(f"no players resolved for {season} week {week} -- the week may not be scheduled")
        if any(p.get("collision") for p in players):
            warnings.append("one or more players played for more than one team in the recent window (a trade) -- "
                            "listed under their latest team")
        return jsonify({"season": season, "week": week, "position": position, "side": side_of(position),
                        "scoring": smeta, "week_range": {"from": lo, "to": hi}, "league_avg_fp_per_game": league_avg,
                        "descriptive_columns": DESCRIPTIVE[position],
                        "player_sort": "projected_fp_per_game (recent baseline x opponent matchup multiplier)",
                        "rankings": ranks, "players": players, "warnings": warnings})
    finally:
        conn.close()


@bp.route("/api/matchups/trends")
def trends():
    season = request.args.get("season", type=int)
    position = (request.args.get("position") or "").upper()
    scoring_id = request.args.get("scoring") or "ppr"
    calibrate = request.args.get("calibrate", default="1") not in ("0", "false", "no")
    teams = [t.strip().upper() for t in (request.args.get("teams") or "").split(",") if t.strip()]
    if not season:
        return jsonify({"error": "season is required"}), 400
    if position not in ALL_GROUPS:
        return jsonify({"error": f"position must be one of {', '.join(ALL_GROUPS)}"}), 400
    conn = _db()
    try:
        try:
            score, smeta = build_scorer(conn, scoring_id, position, calibrate)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        fp = defaultdict(float)
        for r in conn.execute("""SELECT * FROM mart_player_allowed_week WHERE season = ? AND season_type = 'REG'
                                 AND position_group = ?""", (season, position)):
            fp[(r["allowing_team"], r["week"])] += score(r)
        games = sorted(_games(conn, season, 1, 30))
        per_team = defaultdict(list)
        for t, w in games:
            if not teams or t in teams:
                per_team[t].append({"week": w, "games": 1, "fp": fp.get((t, w), 0.0)})
        series = []
        for t in sorted(per_team):
            pts = per_team[t]
            weekly, rolling = [], []
            for i, p in enumerate(pts):
                weekly.append({"week": p["week"], "fp_allowed": round(p["fp"], 2), "fp_allowed_per_game": round(p["fp"], 2)})
                w = pts[max(0, i - 3):i + 1]
                sg, sf = sum(x["games"] for x in w), sum(x["fp"] for x in w)
                rolling.append({"week": p["week"], "weeks_in_window": len(w), "fp_allowed_per_game": round(sf / sg, 2) if sg else None})
            tg, tf = sum(p["games"] for p in pts), sum(p["fp"] for p in pts)
            series.append({"team": t, "season_fp_allowed_per_game": round(tf / tg, 2) if tg else None,
                           "weekly": weekly, "last4_rolling": rolling})
        return jsonify({"season": season, "position": position, "side": side_of(position), "scoring": smeta,
                        "series": series})
    finally:
        conn.close()
