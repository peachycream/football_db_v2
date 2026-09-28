"""Player Dashboard APIs (Phase 7a): /api/dashboard/*.

Ported from v1 app/dashboard.py, dashboard_tiles.py, dashboard_qb_zones.py,
dashboard_rb_lanes.py, dashboard_idp_alignment.py and dashboard_viz.py with the SAME
JSON contracts (v1's React page is reused unchanged). Reads mart_* only.

The player key is the gsis id (v1: a name slug). What changed, each deliberate:
  * POSITION IS PER SEASON, from the source. A defender's bucket is PFF's position
    that season (DI -> DT, ED -> DE); an offensive player's is nflverse's position in
    his last REG week. v1 used one "current" label for every season (so a player who
    moved from S to LB was pooled as an LB in years he played safety).
  * Retired v1 sources are not carried (REBUILD_DESIGN §8 7a): FPD receiving (WR/TE
    target share, air-yards share, inside-20 targets) is replaced by nflverse; the
    FPD route tree has no successor, so /routes answers has_data = false.
  * Passer rating is the NFL formula on REG totals and CPOE is NGS's weekly CPOE
    weighted by attempts (v1 read NGS's season row, which v2's loader does not keep).
  * Expected tackles/sacks tiles are Phase 7b's own model (§6.1): until it passes
    its gate they render as "model pending", never from the name-matched vendor CSV.
  * League points are MFL's REPORTED scores by exact mfl id -> gsis. Sleeper scoring
    is deferred (§10.3): Sleeper leagues are listed, locked.
  * v2 has PFF defense and rushing from 2016, so the IDP-alignment section and the RB
    PFF chips cover 2016+ (v1: 2023+).
"""
import math
from datetime import date

from flask import Blueprint, jsonify, request

from fdb.scoring import STAT_EVENTS, Scorer, catch_all_rules
from .matchups import _db

bp = Blueprint("dashboard", __name__)

# v1 _OFFENSE / _DEFENSE label maps, plus nflverse's SAF.
_OFFENSE = {"QB": "QB", "RB": "RB", "HB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}
_DEFENSE = {"ED": "DE", "DE": "DE", "EDGE": "DE", "DI": "DT", "DT": "DT", "IDL": "DT", "DL": "DT", "NT": "DT",
            "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB", "CB": "CB", "S": "S", "FS": "S", "SS": "S", "SAF": "S",
            "DB": "S"}
PENDING = "model pending (Phase 7b)"

# House default IDP scoring, v1 dashboard.py verbatim (PFF season counts). Tackle family first.
DEFAULT_IDP = [("tackles", 1.25, "T"), ("assists", 0.75, "T"), ("tackles_for_loss", 3, "T"), ("sacks", 5, "N"),
               ("hits", 2, "N"), ("interceptions", 6, "N"), ("pass_break_ups", 4, "N"), ("forced_fumbles", 4, "N"),
               ("fumble_recoveries", 3, "N")]
TACKLE_COLS = ("def_tackles", "def_assists", "def_tfl")
IDP_COLS = [c for c in STAT_EVENTS if c.startswith("def_")]


def _bucket(pos):
    if pos is None:
        return None, None
    p = pos.strip().upper()
    if p in _OFFENSE:
        return "offense", _OFFENSE[p]
    if p in _DEFENSE:
        return "defense", _DEFENSE[p]
    return None, None


def _ph(n):
    return ",".join("?" * n)


def _season_arg():
    s = request.args.get("season", type=int)
    return s


def _default_season(conn):
    r = conn.execute("SELECT MAX(season) FROM mart_player_week WHERE season_type = 'REG'").fetchone()
    return r[0]


def _league(league_id):
    """'mfl:30590:2025' -> ('mfl', '30590'); 'default' / '' -> (None, None)."""
    parts = (league_id or "").split(":")
    if len(parts) >= 2 and parts[0] in ("mfl", "sleeper"):
        return parts[0], parts[1]
    return None, None


# ── per-season position ─────────────────────────────────────────────────────
def season_positions(conn, season, gsis=None):
    """gsis -> (side, bucket, label) for one season: PFF defense position if the player
    has a PFF defensive line that season at a defensive position, unless nflverse's last
    REG week lists him at an offensive position."""
    where, args = ("", ()) if gsis is None else (f" AND gsis_id IN ({_ph(len(gsis))})", tuple(gsis))
    off = {}
    for g, pos in conn.execute(f"""
            SELECT m.gsis_id, m.position FROM mart_player_week m
            JOIN (SELECT gsis_id, MAX(week) w FROM mart_player_week WHERE season = ? AND season_type = 'REG'
                  AND position IS NOT NULL{where} GROUP BY gsis_id) x ON x.gsis_id = m.gsis_id AND x.w = m.week
            WHERE m.season = ? AND m.season_type = 'REG'""", (season, *args, season)):
        off[g] = pos
    dfn = {}
    for g, pos, grp in conn.execute(f"""SELECT gsis_id, pff_position, position_group FROM mart_pff_defense_season
                                        WHERE season = ? AND gsis_id IS NOT NULL AND snaps_total > 0{where}""", (season, *args)):
        if grp in ("DE", "DT", "LB", "CB", "S"):
            dfn[g] = (pos, grp)
    out = {}
    for g in set(off) | set(dfn):
        side, b = _bucket(off.get(g))
        if side == "offense":
            out[g] = ("offense", b, off[g])
        elif g in dfn:
            out[g] = ("defense", dfn[g][1], dfn[g][0])
        elif side:
            out[g] = (side, b, off[g])
    return out


def player_position(conn, gsis, season):
    """(side, bucket, label) for a player-season; falls back to the nearest season with data,
    then to players.position."""
    p = season_positions(conn, season, [gsis]).get(gsis)
    if p:
        return p
    for (s,) in conn.execute("""SELECT season FROM (SELECT season FROM mart_player_week WHERE gsis_id = ?
                                UNION SELECT season FROM mart_pff_defense_season WHERE gsis_id = ?)
                                ORDER BY ABS(season - ?)""", (gsis, gsis, season)):
        p = season_positions(conn, s, [gsis]).get(gsis)
        if p:
            return p
    r = conn.execute("SELECT position FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
    side, b = _bucket(r[0] if r else None)
    return side, b, (r[0] if r else None)


def _season_frac(conn, season):
    wk = conn.execute("SELECT MAX(week) FROM mart_player_week WHERE season = ? AND season_type = 'REG'", (season,)).fetchone()[0]
    if not wk:
        return 1.0
    return min(1.0, wk / (18 if season >= 2021 else 17))


def _max_week(conn, table, season):
    r = conn.execute(f"SELECT MAX(week) FROM {table} WHERE season = ? AND season_type = 'REG'", (season,)).fetchone()
    return r[0] if r and r[0] else 18


# ── shared maps ─────────────────────────────────────────────────────────────
def off_games(conn, season, pids):
    if not pids:
        return {}
    return dict(conn.execute(f"""SELECT gsis_id, COUNT(DISTINCT week) FROM mart_player_week
        WHERE season = ? AND season_type = 'REG' AND gsis_id IN ({_ph(len(pids))})
          AND (COALESCE(offense_snaps, 0) > 0 OR COALESCE(carries, 0) > 0 OR COALESCE(targets, 0) > 0
               OR COALESCE(pass_attempts, 0) > 0) GROUP BY gsis_id""", (season, *pids)).fetchall())


def def_games(conn, season, pids):
    if not pids:
        return {}
    return dict(conn.execute(f"SELECT gsis_id, games FROM mart_pff_defense_season WHERE season = ? AND gsis_id IN ({_ph(len(pids))})",
                             (season, *pids)).fetchall())


def default_idp(row):
    """(total, non-tackle share) from a PFF season line under the house default."""
    if row is None:
        return None, None
    t = sum((row[c] or 0) * w for c, w, b in DEFAULT_IDP if b == "T")
    n = sum((row[c] or 0) * w for c, w, b in DEFAULT_IDP if b == "N")
    return t + n, (100.0 * n / (t + n) if t + n else None)


def league_points(conn, season, league_num, pids):
    if not pids or not league_num:
        return {}
    return dict(conn.execute(f"""SELECT gsis_id, SUM(score) FROM mart_player_league_points_week
        WHERE season = ? AND league_id = ? AND gsis_id IN ({_ph(len(pids))}) GROUP BY gsis_id""",
                             (season, league_num, *pids)).fetchall())


def points_map(conn, season, league_id, pids, side):
    platform, num = _league(league_id)
    if platform == "mfl":
        return league_points(conn, season, num, pids)
    if platform is not None:
        return {}          # Sleeper: scoring deferred
    if not pids:
        return {}
    if side == "offense":
        return dict(conn.execute(f"""SELECT gsis_id, SUM(fantasy_points_ppr) FROM mart_player_week WHERE season = ?
            AND season_type = 'REG' AND gsis_id IN ({_ph(len(pids))}) GROUP BY gsis_id""", (season, *pids)).fetchall())
    rows = conn.execute(f"SELECT * FROM mart_pff_defense_season WHERE season = ? AND gsis_id IN ({_ph(len(pids))})",
                        (season, *pids)).fetchall()
    return {r["gsis_id"]: default_idp(r)[0] for r in rows}


def nontackle_map(conn, season, league_id, pids):
    """% of IDP fantasy points from non-tackle events (v1 idp_fp_split, catch-all ADDITIVE
    rules per v2 scoring, scored per player-week so bonuses apply)."""
    if not pids:
        return {}
    platform, num = _league(league_id)
    if platform is None:
        rows = conn.execute(f"SELECT * FROM mart_pff_defense_season WHERE season = ? AND gsis_id IN ({_ph(len(pids))})",
                            (season, *pids)).fetchall()
        return {r["gsis_id"]: default_idp(r)[1] for r in rows}
    if platform != "mfl":
        return {}
    rules, _ = catch_all_rules(conn, num)
    if not rules:
        return {}
    tk = {g: Scorer(list(TACKLE_COLS), rules=rules.get(g, {})) for g in ("DT", "DE", "LB", "CB", "S")}
    nt = {g: Scorer([c for c in IDP_COLS if c not in TACKLE_COLS], rules=rules.get(g, {})) for g in tk}
    acc = {}
    for r in conn.execute(f"""SELECT * FROM mart_player_allowed_week WHERE season = ? AND side = 'def'
                              AND gsis_id IN ({_ph(len(pids))})""", (season, *pids)):
        g = r["position_group"]
        if g not in tk:
            continue
        a = acc.setdefault(r["gsis_id"], [0.0, 0.0])
        a[0] += tk[g](r)
        a[1] += nt[g](r)
    return {p: (100.0 * n / (t + n) if t + n else None) for p, (t, n) in acc.items()}


def _percentile(pv, eligible, vmap, invert=False):
    """v1 dashboard_tiles._percentile: % of the pool with value <= this one (>= if inverted)."""
    if pv is None:
        return None
    vals = [vmap[q] for q in eligible if vmap.get(q) is not None]
    if not vals:
        return None
    if invert:
        return round(100 * sum(1 for x in vals if x >= pv) / len(vals))
    return round(100 * sum(1 for x in vals if x <= pv) / len(vals))


# ── search / header / seasons / players / leagues ──────────────────────────
@bp.route("/api/dashboard/search")
def search():
    q = (request.args.get("q") or "").strip()
    limit = min(request.args.get("limit", 20, type=int), 50)
    if len(q) < 2:
        return jsonify([])
    conn = _db()
    try:
        rows = conn.execute("""SELECT gsis_id AS player_id, full_name, position, team FROM mart_player_profile
                               WHERE full_name LIKE ? ORDER BY LENGTH(full_name) LIMIT ?""", (f"%{q}%", limit * 3)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["side"], d["bucket"] = _bucket(d["position"])
        if d["bucket"]:
            out.append(d)
    return jsonify(out[:limit])


def _age(birth, season):
    try:
        by, bm, bd = (int(x) for x in str(birth)[:10].split("-"))
        return season - by - ((9, 1) < (bm, bd))
    except Exception:
        return None


@bp.route("/api/dashboard/header")
def header():
    gsis = (request.args.get("player_id") or "").strip()
    league_id = (request.args.get("league_id") or "default").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        out = {"player_id": gsis, "full_name": prow["full_name"], "position": label, "bucket": bucket, "side": side,
               "team": prow["team"], "season": season, "league_id": league_id, "age": _age(prow["birth_date"], season),
               "draft_year": prow["draft_year"], "fantasy_total": None, "games": None, "fantasy_ppg": None,
               "fantasy_source": None, "scoring_label": None}
        out["games"] = ((off_games if side == "offense" else def_games)(conn, season, [gsis]).get(gsis) or None) if side else None
        platform, _ = _league(league_id)
        if platform is None:
            out["scoring_label"] = "Default (PPR)" if side == "offense" else "Default (IDP)"
            out["fantasy_source"] = "default_ppr" if side == "offense" else "default_idp"
        else:
            out["scoring_label"] = "Sleeper scoring" if platform == "sleeper" else "MFL scoring"
            out["fantasy_source"] = "fantasy_scores"
        tot = points_map(conn, season, league_id, [gsis], side).get(gsis) if side else None
        out["fantasy_total"] = round(tot, 1) if tot is not None else None
        if out["fantasy_total"] is not None and out["games"]:
            out["fantasy_ppg"] = round(out["fantasy_total"] / out["games"], 1)
        return jsonify(out)
    finally:
        conn.close()


@bp.route("/api/dashboard/available-seasons")
def available_seasons():
    gsis = (request.args.get("player_id") or "").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        if conn.execute("SELECT 1 FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone() is None:
            return jsonify({"error": "player not found"}), 404
        off = {r[0] for r in conn.execute("""SELECT DISTINCT season FROM mart_player_week WHERE gsis_id = ? AND season_type = 'REG'
            AND (COALESCE(offense_snaps, 0) > 0 OR COALESCE(carries, 0) > 0 OR COALESCE(targets, 0) > 0
                 OR COALESCE(pass_attempts, 0) > 0)""", (gsis,))}
        dfn = {r[0] for r in conn.execute("""SELECT DISTINCT season FROM mart_pff_defense_season WHERE gsis_id = ? AND games > 0
            AND position_group IN ('DE', 'DT', 'LB', 'CB', 'S')""", (gsis,))}
        seasons = sorted(off | dfn, reverse=True)
        side = player_position(conn, gsis, seasons[0])[0] if seasons else _bucket(None)[0]
        return jsonify({"player_id": gsis, "side": side, "seasons": seasons, "most_recent": seasons[0] if seasons else None})
    finally:
        conn.close()


@bp.route("/api/dashboard/players")
def players_list():
    league_id = (request.args.get("league_id") or "default").strip()
    bucket = (request.args.get("bucket") or "").strip() or None
    team = (request.args.get("team") or "").strip() or None
    limit = min(request.args.get("limit", 100, type=int), 300)
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        pos = season_positions(conn, season)
        teams = dict(conn.execute("""SELECT m.gsis_id, m.team FROM mart_player_week m
            JOIN (SELECT gsis_id, MAX(week) w FROM mart_player_week WHERE season = ? AND season_type = 'REG' GROUP BY gsis_id) x
              ON x.gsis_id = m.gsis_id AND x.w = m.week WHERE m.season = ? AND m.season_type = 'REG'""", (season, season)))
        pids = [g for g, (s, b, _) in pos.items() if (not bucket or b == bucket) and (not team or teams.get(g) == team)]
        pts = {}
        for side in ("offense", "defense"):
            sp = [g for g in pids if pos[g][0] == side]
            pts.update(points_map(conn, season, league_id, sp, side))
        names = dict(conn.execute(f"SELECT gsis_id, full_name FROM mart_player_profile WHERE gsis_id IN ({_ph(len(pids))})",
                                  pids).fetchall()) if pids else {}
        rows = [{"player_id": g, "full_name": names.get(g), "position": pos[g][2], "team": teams.get(g),
                 "fantasy_total": round(pts[g], 1), "side": pos[g][0], "bucket": pos[g][1]}
                for g in pids if pts.get(g) is not None]
        rows.sort(key=lambda d: -d["fantasy_total"])
        return jsonify(rows[:limit])
    finally:
        conn.close()


@bp.route("/api/dashboard/leagues")
def leagues():
    conn = _db()
    try:
        season = _default_season(conn)
        scored = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("""SELECT league_id, COUNT(*), COUNT(DISTINCT week), SUM(score)
            FROM mart_player_league_points_week WHERE season = ? GROUP BY league_id""", (season,))}
        out = []
        for num, name, _ in conn.execute("SELECT league_id, name, season FROM mart_mfl_leagues"):
            n, wk, pts = scored.get(num, (0, 0, None))
            enabled = bool(n and pts)
            out.append({"league_id": f"mfl:{num}:{season}", "label": name, "platform": "mfl", "enabled": enabled,
                        "reason": None if enabled else (f"no {season} scoring yet" if not n else "scoring not computed (all 0)"),
                        "weeks": wk})
        for lid, name in conn.execute("""SELECT l.league_id, l.name FROM core_sleeper_league l
                JOIN (SELECT league_id, MAX(season) s FROM core_sleeper_league GROUP BY league_id) m
                  ON m.league_id = l.league_id AND m.s = l.season"""):
            out.append({"league_id": f"sleeper:{lid}", "label": name, "platform": "sleeper", "enabled": False,
                        "reason": "Sleeper scoring deferred (REBUILD_DESIGN §10.3)", "weeks": 0})
        out.sort(key=lambda d: (not d["enabled"], 0 if d["league_id"].startswith("mfl:30590:") else 1, (d["label"] or "").lower()))
        return jsonify(out)
    finally:
        conn.close()


# ── tiles ───────────────────────────────────────────────────────────────────
def _count(expr):
    return {"kind": "count", "expr": expr, "fmt": "n1", "pctile": "compute"}


def _pending(n, label, star=False):
    return {"n": n, "label": label, "star": star, "kind": "pending"}


_WR_TE_COMMON = {
    "ts": {"label": "Target Share", "kind": "wrate", "rate": "target_share", "wt": "targets", "fmt": "pct_frac", "pctile": "compute"},
    "ays": {"label": "Air Yards Share", "kind": "wrate", "rate": "air_yards_share", "wt": "targets", "fmt": "pct_frac", "pctile": "compute"},
}
TILE_SPECS = {
    "QB": [
        {"n": 1, "label": "Pass Yards", **_count("pass_yards")},
        {"n": 2, "label": "Pass Att", **_count("pass_attempts")},
        {"n": 3, "label": "Pass TDs", **_count("pass_tds"), "warn": True},
        {"n": 4, "label": "Rush Yards", **_count("rush_yards")},
        {"n": 5, "label": "Rush Att", **_count("carries")},
        {"n": 6, "label": "Passer Rating", "kind": "passer_rating", "fmt": "n1", "pctile": "compute"},
        {"n": 7, "label": "PFF Pass Grade", "kind": "grade", "col": "grades_pass", "fmt": "grade", "pctile": "compute"},
        {"n": 8, "label": "CPOE", "kind": "ngs_cpoe", "fmt": "cpoe", "pctile": "compute"},
        {"n": 9, "label": "YPA", "kind": "ratio", "num": "pass_yards", "den": "pass_attempts", "fmt": "x1", "pctile": "compute"},
    ],
    "RB": [
        {"n": 1, "label": "Expected FP", "kind": "expcount", "col": "total_fantasy_points_exp", "fmt": "n1", "pctile": "compute", "warn": True},
        {"n": 2, "label": "Touches", **_count("COALESCE(carries,0)+COALESCE(receptions,0)")},
        {"n": 3, "label": "Rush Yards", **_count("rush_yards")},
        {"n": 4, "label": "Carries", **_count("carries")},
        {"n": 5, "label": "Targets", **_count("targets")},
        {"n": 6, "label": "Snap Share", "star": True, "kind": "wrate", "rate": "offense_pct", "wt": "offense_snaps", "fmt": "pct_frac", "pctile": "compute"},
        {"n": 7, "label": "Target Share", "star": True, "kind": "wrate", "rate": "target_share", "wt": "offense_snaps", "fmt": "pct_frac", "pctile": "compute"},
        {"n": 8, "label": "Routes", "kind": "routes", "fmt": "n1", "pctile": "compute"},
        {"n": 9, "label": "PFF Rush Grade", "kind": "grade", "col": "grades_run", "fmt": "grade", "pctile": "compute"},
    ],
    "WR": [
        {"n": 1, "star": True, **_WR_TE_COMMON["ts"]},
        {"n": 2, "label": "Receptions", "star": True, **_count("receptions")},
        {"n": 3, "label": "Rec Yards", "star": True, **_count("rec_yards")},
        {"n": 4, "label": "Targets", "star": True, **_count("targets")},
        {"n": 5, "label": "PFF Rec Grade", "star": True, "kind": "grade", "col": "grades_offense", "fmt": "grade", "pctile": "compute"},
        {"n": 6, "label": "Expected FP", "star": True, "kind": "expcount", "col": "rec_fantasy_points_exp", "fmt": "n1", "pctile": "compute"},
        {"n": 7, "star": True, **_WR_TE_COMMON["ays"]},
        {"n": 8, "label": "Route Grade", "star": True, "kind": "grade", "col": "grades_pass_route", "fmt": "grade", "pctile": "compute"},
        {"n": 9, "label": "Inside-20 Tgts", **_count("rz_targets")},
    ],
    "TE": [
        {"n": 1, "star": True, **_WR_TE_COMMON["ts"]},
        {"n": 2, "label": "Receptions", **_count("receptions")},
        {"n": 3, "label": "Rec Yards", **_count("rec_yards")},
        {"n": 4, "label": "Targets", **_count("targets")},
        {"n": 5, "star": True, **_WR_TE_COMMON["ays"]},
        {"n": 6, "label": "WOPR", "star": True, "kind": "wrate", "rate": "wopr", "wt": "offense_snaps", "fmt": "x2", "pctile": "compute"},
        {"n": 7, "label": "Expected FP", "kind": "expcount", "col": "rec_fantasy_points_exp", "fmt": "n1", "pctile": "compute"},
        {"n": 8, "label": "Route Grade", "kind": "grade", "col": "grades_pass_route", "fmt": "grade", "pctile": "compute"},
        {"n": 9, "label": "Snap Share", "kind": "wrate", "rate": "offense_pct", "wt": "offense_snaps", "fmt": "pct_frac", "pctile": "compute"},
    ],
}
_PTS = [{"n": 4, "label": "IDP Pts", "kind": "points_total", "fmt": "n1", "pctile": "compute", "league_dep": True},
        {"n": 5, "label": "IDP Pts/G", "kind": "points_pg", "fmt": "n1", "pctile": "compute", "league_dep": True}]
_GRADES = [{"n": 7, "label": "PFF Def Grade", "kind": "dgrade", "col": "grade_defense", "fmt": "grade", "pctile": "compute"},
           {"n": 8, "label": "PFF Run-Def", "kind": "dgrade", "col": "grade_run_defense", "fmt": "grade", "pctile": "compute"}]
_EDGE_INT = [_pending(1, "Exp Sack %ile", True), _pending(2, "Exp Sacks/G"), _pending(3, "Sacks vs Exp", True), *_PTS,
             _pending(6, "Tackles vs Exp", True), *_GRADES,
             {"n": 9, "label": "PFF Pass-Rush", "kind": "dgrade", "col": "grade_pass_rush", "fmt": "grade", "pctile": "compute"}]
_COV = {"n": 9, "label": "PFF Coverage", "kind": "dgrade", "col": "grade_coverage", "fmt": "grade", "pctile": "compute"}
TILE_SPECS.update({
    "DE": _EDGE_INT, "DT": _EDGE_INT,
    "LB": [_pending(1, "Tackles vs Exp", True), _pending(2, "Run Tkl vs Exp", True), _pending(3, "Pass Tkl vs Exp", True),
           *_PTS, _pending(6, "Tkl vs Exp/G"), *_GRADES, _COV],
    "CB": [_pending(1, "Tackles vs Exp", True), _pending(2, "Run Tkl vs Exp", True),
           {"n": 3, "label": "Slot Snap Rate", "kind": "snaprate", "col": "snaps_slot", "fmt": "pct_frac", "pctile": "compute"},
           *_PTS, {"n": 6, "label": "% Non-Tackle FP", "star": True, "kind": "nontackle_pct", "fmt": "pct_as",
                   "pctile": "compute", "league_dep": True}, *_GRADES, _COV],
    "S": [_pending(1, "Tackles vs Exp", True), _pending(2, "Run Tkl vs Exp", True),
          {"n": 3, "label": "Box Snap Rate", "kind": "snaprate", "col": "snaps_box", "fmt": "pct_frac", "pctile": "compute"},
          *_PTS, {"n": 6, "label": "% Non-Tackle FP", "star": True, "kind": "nontackle_pct", "fmt": "pct_as",
                  "pctile": "compute", "league_dep": True}, *_GRADES, _COV],
})
_PER_GAME = {"count", "expcount", "points_pg", "routes"}


def pool_ids(conn, bucket, season, pos):
    f = _season_frac(conn, season)
    if bucket == "QB":
        return {g for g, d in conn.execute("SELECT gsis_id, dropbacks FROM mart_pff_qb_dropbacks_season WHERE season = ?", (season,))
                if d is not None and d >= 150 * f and pos.get(g, (None, None))[1] == "QB"}
    if bucket == "RB":
        return {g for g, c, s in conn.execute("""SELECT gsis_id, SUM(COALESCE(carries, 0)), SUM(COALESCE(offense_snaps, 0))
                FROM mart_player_week WHERE season = ? AND season_type = 'REG' GROUP BY gsis_id""", (season,))
                if pos.get(g, (None, None))[1] == "RB" and (c >= 50 * f or s >= 100 * f)}
    if bucket in ("WR", "TE"):
        return {g for g, r in conn.execute("""SELECT gsis_id, SUM(routes) FROM mart_pff_receiving_week WHERE season = ?
                AND season_type = 'REG' GROUP BY gsis_id""", (season,)) if r and r >= 100 * f and pos.get(g, (None, None))[1] == bucket}
    return {g for g, s in conn.execute("SELECT gsis_id, snaps_total FROM mart_pff_defense_season WHERE season = ? AND position_group = ?",
                                       (season, bucket)) if g and s and s >= 100 * f and pos.get(g, (None, None))[1] == bucket}


def _passer_rating(att, comp, yds, td, ints):
    if not att:
        return None
    a = max(0, min(((comp / att) - 0.3) * 5, 2.375))
    b = max(0, min(((yds / att) - 3) * 0.25, 2.375))
    c = max(0, min((td / att) * 20, 2.375))
    d = max(0, min(2.375 - ((ints / att) * 25), 2.375))
    return (a + b + c + d) / 6 * 100


def _value_map(conn, season, spec, pids, gmap, league_id):
    k, ph, reg = spec["kind"], _ph(len(pids)), "season = ? AND season_type = 'REG'"
    per_game = lambda m: {p: (v / gmap[p] if gmap.get(p) and v is not None else None) for p, v in m.items()}
    q = lambda sql: dict(conn.execute(sql, (season, *pids)).fetchall())
    if k == "count":
        return per_game(q(f"SELECT gsis_id, SUM(COALESCE({spec['expr']}, 0)) FROM mart_player_week WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id"))
    if k == "expcount":
        return per_game(q(f"SELECT gsis_id, SUM(COALESCE({spec['col']}, 0)) FROM mart_ff_opportunity_week WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id"))
    if k == "wrate":
        r, w = spec["rate"], spec["wt"]
        return q(f"SELECT gsis_id, SUM({r} * {w}) * 1.0 / NULLIF(SUM(CASE WHEN {r} IS NOT NULL THEN {w} END), 0) FROM mart_player_week "
                 f"WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id")
    if k == "ratio":
        return q(f"SELECT gsis_id, SUM({spec['num']}) * 1.0 / NULLIF(SUM({spec['den']}), 0) FROM mart_player_week WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id")
    if k == "passer_rating":
        return {g: _passer_rating(a or 0, c or 0, y or 0, t or 0, i or 0) for g, a, c, y, t, i in conn.execute(
            f"""SELECT gsis_id, SUM(pass_attempts), SUM(completions), SUM(pass_yards), SUM(pass_tds), SUM(interceptions)
                FROM mart_player_week WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id""", (season, *pids))}
    if k == "ngs_cpoe":
        return q(f"SELECT gsis_id, SUM(cpoe * attempts) / NULLIF(SUM(attempts), 0) FROM mart_ngs_passing_week WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id")
    if k == "grade":
        return q(f"SELECT gsis_id, {spec['col']} FROM mart_pff_offense_season WHERE season = ? AND gsis_id IN ({ph})")
    if k == "routes":
        return per_game(q(f"SELECT gsis_id, SUM(routes) FROM mart_pff_receiving_week WHERE {reg} AND gsis_id IN ({ph}) GROUP BY gsis_id"))
    if k == "dgrade":
        return q(f"SELECT gsis_id, {spec['col']} FROM mart_pff_defense_season WHERE season = ? AND gsis_id IN ({ph})")
    if k == "snaprate":
        return q(f"SELECT gsis_id, {spec['col']} * 1.0 / NULLIF(snaps_total, 0) FROM mart_pff_defense_season WHERE season = ? AND gsis_id IN ({ph})")
    if k == "points_total":
        return points_map(conn, season, league_id, list(pids), "defense")
    if k == "points_pg":
        return per_game(points_map(conn, season, league_id, list(pids), "defense"))
    if k == "nontackle_pct":
        return nontackle_map(conn, season, league_id, list(pids))
    return {}


def _fmt(v, f):
    if v is None:
        return "n/a"
    if f in ("n1", "x1", "grade"):
        return f"{v:.1f}"
    if f in ("n2", "x2"):
        return f"{v:.2f}"
    if f == "cpoe":
        return f"{v:+.1f}%"
    if f == "plus1":
        return f"{v:+.1f}"
    if f == "pct_frac":
        return f"{v * 100:.1f}%"
    if f == "pct_as":
        return f"{v:.1f}%"
    return f"{v}"


@bp.route("/api/dashboard/tiles")
def tiles():
    gsis = (request.args.get("player_id") or "").strip()
    league_id = (request.args.get("league_id") or "default").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        pos = season_positions(conn, season)
        eligible = pool_ids(conn, bucket, season, pos) if bucket else set()
        pids = eligible | {gsis}
        gmap = (off_games if side == "offense" else def_games)(conn, season, list(pids))
        out = []
        for spec in TILE_SPECS.get(bucket or "", []):
            if spec["kind"] == "pending":
                out.append({"n": spec["n"], "label": spec["label"], "star": spec.get("star", False), "display": "—",
                            "raw": None, "sub": PENDING, "percentile": None, "per_game": False, "league_dep": False,
                            "warn": False})
                continue
            vmap = _value_map(conn, season, spec, list(pids), gmap, league_id)
            pv = vmap.get(gsis)
            pct = _percentile(pv, eligible, vmap, invert=bool(spec.get("invert"))) if gsis in eligible else None
            out.append({"n": spec["n"], "label": spec["label"], "star": bool(spec.get("star")), "display": _fmt(pv, spec["fmt"]),
                        "raw": pv, "sub": None, "percentile": pct, "per_game": spec["kind"] in _PER_GAME,
                        "league_dep": bool(spec.get("league_dep")), "warn": bool(spec.get("warn"))})
        return jsonify({"player_id": gsis, "full_name": prow["full_name"], "position": label, "bucket": bucket, "side": side,
                        "team": prow["team"], "season": season, "league_id": league_id, "games": gmap.get(gsis),
                        "pool_size": len(eligible), "tiles": out})
    finally:
        conn.close()


# ── snaps / routes ──────────────────────────────────────────────────────────
@bp.route("/api/dashboard/snaps")
def snaps():
    gsis = (request.args.get("player_id") or "").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        out = {"player_id": gsis, "full_name": prow["full_name"], "position": label, "bucket": bucket, "side": side,
               "season": season, "side_label": None, "points": [], "season_high": None, "collision_weeks": 0}
        if side not in ("offense", "defense"):
            return jsonify(out)
        col = "offense" if side == "offense" else "defense"
        out["side_label"] = "Offensive snaps" if side == "offense" else "Defensive snaps"
        pts = []
        for r in conn.execute(f"""SELECT week, {col}_snaps s, {col}_pct p, snap_teams, n_snap_teams FROM mart_player_week
                                  WHERE gsis_id = ? AND season = ? AND season_type = 'REG' AND {col}_snaps > 0 ORDER BY week""",
                              (gsis, season)):
            pts.append({"week": r["week"], "snaps": int(r["s"]), "snap_pct": round((r["p"] or 0) * 100, 1),
                        "team": r["snap_teams"], "multi_team": (r["n_snap_teams"] or 0) > 1})
        out["points"] = pts
        out["season_high"] = max((p["snaps"] for p in pts), default=0) or None
        out["collision_weeks"] = sum(p["multi_team"] for p in pts)
        return jsonify(out)
    finally:
        conn.close()


@bp.route("/api/dashboard/routes")
def routes():
    """v1's route tree read FPD's per-route weekly file, a retired source that v2 does not
    carry (REBUILD_DESIGN §8 7a). Same shape, has_data false: the page hides the panel."""
    gsis = (request.args.get("player_id") or "").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        return jsonify({"player_id": gsis, "full_name": prow["full_name"], "position": label, "bucket": bucket, "side": side,
                        "season": season, "has_data": False, "total_routes": 0, "total_targets": 0, "weeks": 0, "spokes": []})
    finally:
        conn.close()


# ── QB zones ────────────────────────────────────────────────────────────────
ZONE_DIRECTIONS = ["left", "middle", "right"]
ZONE_DEPTHS = ["blos", "short", "medium", "deep"]


def _chip(v_map, key, eligible, invert=False):
    v = v_map.get(key)
    if v is None:
        return None
    rank = {k: -x for k, x in v_map.items()} if invert else v_map
    return {"value": round(v, 4), "pct": _percentile(-v if invert else v, eligible, rank)}


@bp.route("/api/dashboard/qb-zones")
def qb_zones():
    gsis = (request.args.get("player_id") or "").strip()
    league_id = (request.args.get("league_id") or "").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        base = {"player_id": gsis, "full_name": prow["full_name"], "position": label, "season": season}
        if bucket != "QB":
            return jsonify({**base, "eligible": False, "reason": "not a QB"})
        if season < 2016:
            return jsonify({**base, "eligible": False, "reason": "nflfastR cp coverage begins 2016"})
        floor = max(1, math.ceil(200 * min(_max_week(conn, "mart_qb_dropback_week", season), 18) / 18))
        tot = {r["gsis_id"]: dict(r) for r in conn.execute("""SELECT gsis_id, SUM(dropbacks) dropbacks, SUM(sum_epa) sum_epa,
                SUM(successes) successes, SUM(attempts) attempts, SUM(completions) completions, SUM(cpoe_attempts) cpoe_attempts,
                SUM(sum_cp) sum_cp FROM mart_qb_dropback_week WHERE season = ? AND season_type = 'REG' GROUP BY gsis_id""", (season,))}
        own = tot.get(gsis)
        dropbacks = own["dropbacks"] if own else 0
        if not own or dropbacks < floor:
            return jsonify({**base, "eligible": False, "reason": f"below {floor}-dropback floor ({dropbacks} dropbacks)",
                            "dropbacks": dropbacks, "min_dropbacks": floor})
        eligible = {g for g, t in tot.items() if t["dropbacks"] >= floor} | {gsis}
        pool = {g: tot[g] for g in eligible}
        epa = {g: t["sum_epa"] / t["dropbacks"] for g, t in pool.items() if t["dropbacks"]}
        cpoe = {g: 100 * (t["completions"] - t["sum_cp"]) / t["cpoe_attempts"] for g, t in pool.items() if t["cpoe_attempts"]}
        succ = {g: t["successes"] / t["dropbacks"] for g, t in pool.items() if t["dropbacks"]}
        fp = {}
        platform, num = _league(league_id)
        if platform == "mfl":
            for g, p in league_points(conn, season, num, list(eligible)).items():
                if pool[g]["dropbacks"] and p is not None:
                    fp[g] = p / pool[g]["dropbacks"]
        header = {"epa_per_dropback": _chip(epa, gsis, eligible), "cpoe": _chip(cpoe, gsis, eligible),
                  "success_rate": _chip(succ, gsis, eligible), "fp_per_dropback": _chip(fp, gsis, eligible) if fp else None}
        zr = {(r["zone_direction"], r["zone_depth"]): r for r in conn.execute("""SELECT zone_direction, zone_depth,
                SUM(attempts) attempts, SUM(completions) completions, SUM(cpoe_attempts) cpoe_attempts, SUM(sum_cp) sum_cp,
                SUM(sum_epa) sum_epa FROM mart_qb_pass_zones_week WHERE gsis_id = ? AND season = ? AND season_type = 'REG'
                GROUP BY zone_direction, zone_depth""", (gsis, season))}
        total = sum(r["attempts"] for r in zr.values()) or 1
        zones = []
        for d in ZONE_DIRECTIONS:
            for dp in ZONE_DEPTHS:
                r = zr.get((d, dp))
                a = r["attempts"] if r else 0
                zones.append({"direction": d, "depth": dp, "attempts": a, "att_share": round(a / total, 4),
                              "comp_pct": round(r["completions"] / a, 4) if r and a else None,
                              "cpoe": round(100 * (r["completions"] - r["sum_cp"]) / r["cpoe_attempts"], 2) if r and r["cpoe_attempts"] else None,
                              "epa_per_att": round(r["sum_epa"] / a, 4) if r and a else None})
        return jsonify({**base, "eligible": True, "zones": zones, "header": header, "dropbacks": dropbacks, "min_dropbacks": floor})
    finally:
        conn.close()


# ── RB lanes ────────────────────────────────────────────────────────────────
LANES = ["LE", "LT", "LG", "M", "RG", "RT", "RE"]


@bp.route("/api/dashboard/rb-lanes")
def rb_lanes():
    gsis = (request.args.get("player_id") or "").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        base = {"player_id": gsis, "full_name": prow["full_name"], "position": label, "season": season}
        if bucket != "RB":
            return jsonify({**base, "eligible": False, "reason": "not an RB"})
        floor = max(1, math.ceil(100 * min(_max_week(conn, "mart_rb_run_lanes_week", season), 18) / 18))
        tot = {r["gsis_id"]: dict(r) for r in conn.execute("""SELECT gsis_id, SUM(carries) carries, SUM(yards_sum) yards_sum,
                SUM(sum_epa) sum_epa, SUM(successes) successes FROM mart_rb_run_lanes_week
                WHERE season = ? AND season_type = 'REG' GROUP BY gsis_id""", (season,))}
        own = tot.get(gsis)
        carries = own["carries"] if own else 0
        if not own or carries < floor:
            return jsonify({**base, "eligible": False, "reason": f"below {floor}-carry floor ({carries} carries)",
                            "carries": carries, "min_carries": floor})
        eligible = {g for g, t in tot.items() if t["carries"] >= floor} | {gsis}
        succ = {g: tot[g]["successes"] / tot[g]["carries"] for g in eligible if tot[g]["carries"]}
        mtf, yac, expl, brk = {}, {}, {}, {}
        for r in conn.execute(f"""SELECT gsis_id, SUM(attempts) a, SUM(avoided_tackles) mt, SUM(yards_after_contact) yc,
                SUM(explosive) ex, SUM(breakaway_yards) bk, SUM(yards) y FROM mart_pff_rushing_week
                WHERE season = ? AND season_type = 'REG' AND gsis_id IN ({_ph(len(eligible))}) GROUP BY gsis_id""",
                              (season, *eligible)):
            if not r["a"]:
                continue
            g = r["gsis_id"]
            mtf[g], yac[g], expl[g] = r["mt"] / r["a"], r["yc"] / r["a"], r["ex"] / r["a"]
            if r["y"]:
                brk[g] = r["bk"] / r["y"]
        header = {"mtf_per_att": _chip(mtf, gsis, eligible), "yac_per_att": _chip(yac, gsis, eligible),
                  "explosive_rate": _chip(expl, gsis, eligible), "breakaway_pct": _chip(brk, gsis, eligible),
                  "success_rate": _chip(succ, gsis, eligible)}
        lr = {r["lane"]: r for r in conn.execute("""SELECT lane, SUM(carries) carries, SUM(yards_sum) yards_sum, SUM(sum_epa) sum_epa,
                SUM(successes) successes FROM mart_rb_run_lanes_week WHERE gsis_id = ? AND season = ? AND season_type = 'REG'
                GROUP BY lane""", (gsis, season))}
        lg = {r[0]: (r[2] / r[1] if r[1] else None) for r in conn.execute("""SELECT lane, SUM(carries), SUM(sum_epa)
                FROM mart_rb_run_lanes_week WHERE season = ? AND season_type = 'REG' GROUP BY lane""", (season,))}
        total = sum(r["carries"] for r in lr.values()) or 1
        lanes = []
        for ln in LANES:
            r = lr.get(ln)
            c = r["carries"] if r else 0
            lanes.append({"lane": ln, "carries": c, "carry_share": round(c / total, 4),
                          "ypc": round(r["yards_sum"] / c, 2) if r and c else None,
                          "success_rate": round(r["successes"] / c, 4) if r and c else None,
                          "epa_per_att": round(r["sum_epa"] / c, 4) if r and c else None,
                          "lg_avg_epa_per_att": round(lg[ln], 4) if lg.get(ln) is not None else None})
        return jsonify({**base, "eligible": True, "lanes": lanes, "header": header, "carries": carries, "min_carries": floor})
    finally:
        conn.close()


# ── IDP alignment ───────────────────────────────────────────────────────────
ALIGN = [("dl", "snaps_dl"), ("box", "snaps_box"), ("slot", "snaps_slot"), ("corner", "snaps_corner"), ("fs", "snaps_fs")]
ROLE = [("run_defense", "snaps_run_defense"), ("pass_rush", "snaps_pass_rush"), ("coverage", "snaps_coverage")]


@bp.route("/api/dashboard/idp-alignment")
def idp_alignment():
    gsis = (request.args.get("player_id") or "").strip()
    league_id = (request.args.get("league_id") or "").strip()
    if not gsis:
        return jsonify({"error": "player_id required"}), 400
    conn = _db()
    try:
        season = _season_arg() or _default_season(conn)
        prow = conn.execute("SELECT * FROM mart_player_profile WHERE gsis_id = ?", (gsis,)).fetchone()
        if prow is None:
            return jsonify({"error": "player not found"}), 404
        side, bucket, label = player_position(conn, gsis, season)
        base = {"player_id": gsis, "full_name": prow["full_name"], "position": label, "season": season}
        if side != "defense" or bucket not in ("DE", "DT", "LB", "CB", "S"):
            return jsonify({**base, "eligible": False, "reason": "not a defender"})
        if season < 2016:
            return jsonify({**base, "eligible": False, "reason": "PFF alignment data begins 2016"})
        pool = {r["gsis_id"]: dict(r) for r in conn.execute("""SELECT * FROM mart_pff_defense_season
                WHERE season = ? AND position_group = ? AND gsis_id IS NOT NULL""", (season, bucket))}
        own = pool.get(gsis) or next((dict(r) for r in conn.execute(
            "SELECT * FROM mart_pff_defense_season WHERE season = ? AND gsis_id = ?", (season, gsis))), None)
        total = own["snaps_total"] if own else 0
        wk = conn.execute("SELECT MAX(week) FROM mart_player_week WHERE season = ? AND season_type = 'REG' AND defense_snaps > 0",
                          (season,)).fetchone()[0] or 18
        floor = max(1, math.ceil(250 * min(wk, 18) / 18))
        if not own or not total or total < floor:
            return jsonify({**base, "eligible": False, "reason": f"below {floor}-snap floor ({total or 0} snaps)",
                            "total_snaps": total or 0, "min_snaps": floor, "position_group": bucket})
        pool[gsis] = own
        eligible = {g for g, r in pool.items() if r["snaps_total"] and r["snaps_total"] >= floor} | {gsis}
        z = lambda v: v or 0
        tko = {g: (z(r["tackles"]) + z(r["assists"])) / r["snaps_run_defense"] for g, r in pool.items() if g in eligible and r["snaps_run_defense"]}
        mtr = {g: 100.0 * z(r["missed_tackles"]) / (z(r["tackles"]) + z(r["assists"]) + z(r["missed_tackles"]))
               for g, r in pool.items() if g in eligible and z(r["tackles"]) + z(r["assists"]) + z(r["missed_tackles"])}
        prs = {g: z(r["total_pressures"]) / r["snaps_pass_rush"] for g, r in pool.items() if g in eligible and r["snaps_pass_rush"]}
        cov = {g: r["yards_allowed"] / r["snaps_coverage"] for g, r in pool.items()
               if g in eligible and r["snaps_coverage"] and r["yards_allowed"] is not None}
        fp = {}
        platform, num = _league(league_id)
        if platform == "mfl":
            for g, p in league_points(conn, season, num, list(eligible)).items():
                if pool[g]["snaps_total"] and p is not None:
                    fp[g] = p / pool[g]["snaps_total"]
        header = {"tackle_opp_rate": _chip(tko, gsis, eligible), "missed_tackle_rate": _chip(mtr, gsis, eligible, invert=True),
                  "pressure_rate": _chip(prs, gsis, eligible), "coverage_eff": _chip(cov, gsis, eligible, invert=True),
                  "fp_per_snap": _chip(fp, gsis, eligible) if fp else None}
        align = [{"bucket": b, "snaps": z(own[c]), "share": round(z(own[c]) / total, 4)} for b, c in ALIGN]
        role = [{"bucket": b, "snaps": z(own[c]), "share": round(z(own[c]) / total, 4)} for b, c in ROLE]
        return jsonify({**base, "eligible": True, "alignment": align, "role": role, "header": header,
                        "total_snaps": total, "min_snaps": floor, "position_group": bucket})
    finally:
        conn.close()
