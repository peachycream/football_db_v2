"""Defense target-zone map: where each defense's targets, completions and air yards go, against the league.

Reads mart_def_target_play / mart_def_dropback_week only (schema 058). Counts are summed here and every rate is
computed at read time (rule 4): completion % is completions / targets, never an average of percentages.

Zones are 3 lanes (left / middle / right, FTN's own `loc` lane) x 7 depth bands by air yards. A cell's color is the
defense's per-game rate in that cell divided by the league's per-game rate in the SAME cell (so deep-middle is not
"cold" just because few passes go there), shrunk toward 1 by n / (n + K) so a cell with 2 targets cannot read as an
outlier. The raw counts always ride along for the hover.
"""
from __future__ import annotations

POSITIONS = ("ALL", "WR", "TE", "RB")       # ALL = WR + TE + RB targets (QB / OL / unknown-position targets are in no filter)
LANES = ("L", "M", "R")
BANDS = [(-99, 0, "<0"), (0, 5, "0-4"), (5, 10, "5-9"), (10, 15, "10-14"), (15, 20, "15-19"), (20, 30, "20-29"), (30, 99, "30+")]
SHRINK_K = 6.0                               # cell targets at which the ratio is half-trusted
DEEP = 20                                    # a "deep target" is 20+ air yards
METRICS = ("targets", "completions", "comp_pct", "air_yards")


def band_of(air_yards: int) -> int:
    for i, (lo, hi, _l) in enumerate(BANDS):
        if lo <= air_yards < hi:
            return i
    return len(BANDS) - 1


def _season(conn) -> int | None:
    r = conn.execute("SELECT MAX(season) FROM mart_def_target_play").fetchone()
    return r[0] if r else None


def _weeks(conn, season):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT week FROM mart_def_dropback_week WHERE season = ? ORDER BY week", (season,))]


def _rows(conn, season, weeks, pos):
    sql = ("SELECT defteam, week, lane, air_yards, complete, yards, rec_td, route, name, position, gsis_id "
           "FROM mart_def_target_play WHERE season = ? AND week BETWEEN ? AND ? AND position IN ({})")
    ps = ("WR", "TE", "RB") if pos == "ALL" else (pos,)
    sql = sql.format(",".join("?" * len(ps)))
    return conn.execute(sql, (season, weeks[0], weeks[-1], *ps)).fetchall()


def _cells():
    return [[{"t": 0, "c": 0, "ay": 0, "td": 0} for _ in BANDS] for _ in LANES]


def _agg(rows):
    """team -> {cells, t, c, ay, deep, yards, td, pts}. pts = receiving PPR points allowed (1/rec, 0.1/yd, 6/TD)."""
    out = {}
    for r in rows:
        a = out.setdefault(r["defteam"], {"cells": _cells(), "t": 0, "c": 0, "ay": 0, "deep": 0, "pts": 0.0})
        li, bi = LANES.index(r["lane"]), band_of(r["air_yards"])
        cell = a["cells"][li][bi]
        cell["t"] += 1
        cell["c"] += r["complete"]
        cell["ay"] += r["air_yards"]
        cell["td"] += r["rec_td"]
        a["t"] += 1
        a["c"] += r["complete"]
        a["ay"] += r["air_yards"]
        a["deep"] += 1 if r["air_yards"] >= DEEP else 0
        if r["complete"]:
            a["pts"] += 1 + 0.1 * (r["yards"] or 0) + 6 * r["rec_td"]
    return out


def _games(conn, season, weeks):
    g, d = {}, {}
    for r in conn.execute("SELECT defteam, COUNT(*) n, SUM(dropbacks) db, SUM(epa) epa FROM mart_def_dropback_week "
                          "WHERE season = ? AND week BETWEEN ? AND ? GROUP BY defteam", (season, weeks[0], weeks[-1])):
        g[r["defteam"]] = r["n"]
        d[r["defteam"]] = (r["db"], r["epa"])
    return g, d


def _ratio(team_val, team_g, lg_val, lg_g, n):
    if not team_g or not lg_g or lg_val <= 0:
        return 1.0
    raw = (team_val / team_g) / (lg_val / lg_g)
    w = n / (n + SHRINK_K)
    return 1.0 + (raw - 1.0) * w


def _rank(vals: dict, team: str, higher_is_more: bool = True):
    """1 = allows the most. Returns (rank, of, percentile 0-100 where 100 = allows the most)."""
    order = sorted(vals, key=lambda k: -vals[k] if higher_is_more else vals[k])
    rank = order.index(team) + 1
    n = len(order)
    return rank, n, round(100.0 * (n - rank) / (n - 1), 0) if n > 1 else 50.0


def build(conn, team: str, pos: str = "ALL", last_n: int | None = None) -> dict:
    season = _season(conn)
    if season is None:
        return {"error": "mart_def_target_play is empty"}
    all_weeks = _weeks(conn, season)
    if not all_weeks:
        return {"error": f"no dropback weeks for {season}"}
    weeks = all_weeks[-last_n:] if last_n else all_weeks
    pos = pos if pos in POSITIONS else "ALL"
    rows = _rows(conn, season, weeks, pos)
    agg = _agg(rows)
    games, dbk = _games(conn, season, weeks)
    teams = sorted(games)
    if team not in games:
        return {"error": f"unknown team {team}", "teams": teams}
    me = agg.get(team) or {"cells": _cells(), "t": 0, "c": 0, "ay": 0, "deep": 0, "pts": 0.0}
    g_me = games[team]
    lg_g = sum(games.values())
    lg = {"t": 0, "c": 0, "ay": 0, "deep": 0, "pts": 0.0}
    lg_cells = _cells()
    for tm, a in agg.items():
        for k in lg:
            lg[k] += a[k]
        for li in range(3):
            for bi in range(len(BANDS)):
                for k in ("t", "c", "ay", "td"):
                    lg_cells[li][bi][k] += a["cells"][li][bi][k]

    cells = []
    for li, lane in enumerate(LANES):
        for bi, (_lo, _hi, label) in enumerate(BANDS):
            c, L = me["cells"][li][bi], lg_cells[li][bi]
            n = c["t"]
            cells.append({
                "lane": lane, "band": bi, "label": label, "n": n, "c": c["c"], "ay": c["ay"], "td": c["td"],
                "lg_t_pg": round(L["t"] / lg_g, 3), "lg_c_pct": round(L["c"] / L["t"], 3) if L["t"] else None,
                "ratio": {
                    "targets": _ratio(c["t"], g_me, L["t"], lg_g, n),
                    "completions": _ratio(c["c"], g_me, L["c"], lg_g, n),
                    "comp_pct": (1.0 + ((c["c"] / c["t"]) / (L["c"] / L["t"]) - 1.0) * n / (n + SHRINK_K))
                                if c["t"] and L["t"] and L["c"] else 1.0,
                    "air_yards": _ratio(c["ay"], g_me, L["ay"], lg_g, n),
                },
            })

    # Team-level strip: each metric for all 32 teams, so rank and the league tick come from the same population.
    def per_team(f):
        return {tm: f(a, tm) for tm, a in agg.items() if games.get(tm)}
    comp_pct = per_team(lambda a, tm: a["c"] / a["t"] if a["t"] else 0.0)
    adot = per_team(lambda a, tm: a["ay"] / a["t"] if a["t"] else 0.0)
    deep_rate = per_team(lambda a, tm: a["deep"] / a["t"] if a["t"] else 0.0)
    pts_pg = {tm: a["pts"] / games[tm] for tm, a in agg.items() if games.get(tm)}
    epa_db = {tm: v[1] / v[0] for tm, v in dbk.items() if v[0]}
    for t_ in teams:                                 # a team with no targets in the filter still ranks (at 0)
        pts_pg.setdefault(t_, 0.0)

    def strip(key, label, vals, fmt, note=""):
        if team not in vals:
            return {"key": key, "label": label, "value": None, "note": note}
        rank, n, pct = _rank(vals, team)
        xs = sorted(vals.values())
        return {"key": key, "label": label, "value": vals[team], "league": sum(xs) / len(xs), "lo": xs[0], "hi": xs[-1],
                "rank": rank, "of": n, "pct": pct, "fmt": fmt, "note": note}

    strips = [
        strip("comp_pct", "Completion % allowed", comp_pct, "pct1"),
        strip("adot", "Air yards / target allowed", adot, "num1"),
        strip("deep", "Deep-target rate (20+ air yds)", deep_rate, "pct1"),
        strip("epa", "EPA / dropback allowed", epa_db, "num3", "all dropbacks, not filtered by position"),
    ]

    pts_strip = strip("pts", "Receiving PPR PPG allowed", pts_pg, "num1",
                      "to " + ("WR + TE + RB" if pos == "ALL" else pos))

    dots = [{"lane": r["lane"], "ay": r["air_yards"], "c": r["complete"], "td": r["rec_td"], "yd": r["yards"] or 0,
             "route": r["route"], "name": r["name"], "week": r["week"], "pos": r["position"], "id": r["gsis_id"]}
            for r in rows if r["defteam"] == team]

    return {
        "season": season, "team": team, "pos": pos, "weeks": [weeks[0], weeks[-1]], "all_weeks": all_weeks,
        "games": g_me, "teams": teams, "bands": [b[2] for b in BANDS], "cells": cells, "dots": dots,
        "targets": me["t"], "completions": me["c"],
        "league_games": lg_g, "pts": pts_strip, "strips": strips,
        "td_allowed": sum(c["td"] for row in me["cells"] for c in row),
    }
