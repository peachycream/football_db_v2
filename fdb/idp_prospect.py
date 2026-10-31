"""Phase 15c: NFL outcomes of drafted defenders, years 1-3 -> mart_idp_prospect_outcome (builder `idp_prospect.outcomes`).

The label side of the IDP prospect model. Everything is exact-key: a drafted defender is a core_nflverse_draft_picks row
(side = 'D') with a gsis_id, and his NFL production is mart_player_allowed_week's defensive rows for that same gsis_id.
No name is read anywhere. The draft table's own career columns (games, w_av, def_sacks, ...) are post-draft outcomes and are
never read: the outcome is rebuilt from counts so it is on one scale for every season.

Points: the catch-all rules of LEAGUE (fdb/scoring.py: every rule that names the position applies, additively) scoring each
player-WEEK's counts, summed per season. The rule set is the league's 2026 one, applied to every season, so all seasons share
one scale; it is not MFL's reported number (MFL scores its own tackle stats; ops/phase15c_reconcile.py measures the gap).
Position finish ranks a player's season points among every player of his group that season (PFF's position, the group
he played most snaps at; ties share the best rank). Regular season only; a season counts once it is closed.
"""
from collections import defaultdict

from . import schedule
from .scoring import STAT_EVENTS, Scorer, catch_all_rules

LEAGUE = "30590"
FIRST_DRAFT = 2016          # PFF defensive weekly charting starts 2016, so a rookie class earlier than that has no year 1
GROUPS = ("DT", "DE", "LB", "CB", "S")
MAX_GAMES = 18


def _closed_seasons(conn) -> list[int]:
    return [s for s in schedule.seasons_loaded(conn) if s >= FIRST_DRAFT and schedule.season_is_closed(conn, s)]


def _season_points(conn, seasons, rules) -> dict:
    """{(season, pff 'player_key'): {gsis, games, snaps, points, group_snaps{group: snaps}}} for REG defensive rows."""
    cols = [c for c in STAT_EVENTS if c.startswith("def_")]
    scorers = {g: Scorer(cols, rules=rules.get(g, {})) for g in GROUPS}
    out = {}
    for s in seasons:
        for r in conn.execute("""SELECT * FROM mart_player_allowed_week WHERE season = ? AND season_type = 'REG'
                                 AND side = 'def' AND COALESCE(def_snaps, 0) > 0""", (s,)):
            a = out.setdefault((s, r["player_key"]), {"gsis": r["gsis_id"], "games": 0, "snaps": 0, "points": 0.0,
                                                     "group_snaps": defaultdict(int)})
            a["games"] += 1
            a["snaps"] += r["def_snaps"]
            a["points"] += scorers[r["position_group"]](r)
            a["group_snaps"][r["position_group"]] += r["def_snaps"]
    for a in out.values():
        gs = a["group_snaps"]
        a["group"] = max(gs, key=lambda g: (gs[g], g))
    return out


def _finishes(season_rows) -> dict:
    """{(season, group): {player_key: (finish, n_in_group)}}; ties share the best rank."""
    by = defaultdict(list)
    for (s, key), a in season_rows.items():
        by[(s, a["group"])].append((key, a["points"]))
    out = {}
    for k, xs in by.items():
        pts = sorted((p for _, p in xs), reverse=True)
        first = {}
        for i, p in enumerate(pts, 1):
            first.setdefault(p, i)
        out[k] = ({key: (first[p], len(xs)) for key, p in xs})
    return out


def build(conn) -> dict:
    if not conn.execute("SELECT 1 FROM core_nflverse_draft_picks LIMIT 1").fetchone():
        conn.execute("DELETE FROM mart_idp_prospect_outcome")   # nothing drafted is loaded: nothing to build (a bare seed DB)
        return {"failures": [], "summary": "no draft picks loaded"}
    rules, _ = catch_all_rules(conn, LEAGUE)
    if not rules:
        return {"failures": [f"no mart_mfl_rules rows for league {LEAGUE}"], "summary": "no rules"}
    closed = _closed_seasons(conn)
    last = max(closed) if closed else None
    pop = conn.execute("""SELECT d.gsis_id, d.season, d.pick, p.pff_id FROM core_nflverse_draft_picks d
                          LEFT JOIN core_nflverse_players p ON p.gsis_id = d.gsis_id
                          WHERE d.side = 'D' AND d.season BETWEEN ? AND ? AND d.gsis_id IS NOT NULL
                          ORDER BY d.season, d.pick""", (FIRST_DRAFT, last or 0)).fetchall()
    no_gsis = conn.execute("""SELECT COUNT(*) FROM core_nflverse_draft_picks WHERE side = 'D' AND season BETWEEN ? AND ?
                              AND gsis_id IS NULL""", (FIRST_DRAFT, last or 0)).fetchone()[0]
    rows_by_player = _season_points(conn, closed, rules)
    fin = _finishes(rows_by_player)
    by_gsis = defaultdict(dict)   # gsis -> {season: a}; a player_key is one PFF id, a gsis_id maps to one PFF id
    for (s, key), a in rows_by_player.items():
        if a["gsis"]:
            if s in by_gsis[a["gsis"]]:
                return {"failures": [f"{a['gsis']}: two PFF keys in {s}"], "summary": "duplicate gsis in a season"}
            by_gsis[a["gsis"]][s] = (key, a)

    out = []
    for gsis, draft, pick, pff in pop:
        years = [(k, draft + k - 1) for k in (1, 2, 3) if draft + k - 1 <= last]
        for k, s in years:
            hit = by_gsis.get(gsis, {}).get(s)
            if hit is None:
                out.append((gsis, pff, draft, pick, k, s, len(years), None, 0, 0, 0.0, None, None, 0, 0))
                continue
            key, a = hit
            f, n = fin[(s, a["group"])][key]
            out.append((gsis, pff, draft, pick, k, s, len(years), a["group"], a["games"], a["snaps"], round(a["points"], 4),
                        f, n, int(f <= 12), int(f <= 24)))
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM mart_idp_prospect_outcome")
        conn.executemany("INSERT INTO mart_idp_prospect_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
        fails = checks(conn, closed, len(pop))
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    played = sum(1 for r in out if r[8] > 0)
    return {"failures": fails,
            "summary": f"{len(pop)} drafted defenders 2016-{last} ({no_gsis} without gsis_id skipped), {len(out)} player-years, "
                       f"{played} with a snap, league {LEAGUE} catch-all"}


def checks(conn, closed, n_players) -> list[str]:
    fails = []
    n = conn.execute("SELECT COUNT(DISTINCT gsis_id) FROM mart_idp_prospect_outcome").fetchone()[0]
    if n != n_players:
        fails.append(f"{n} players in the mart, {n_players} drafted defenders expected")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_outcome WHERE games > ? OR games < 0 OR snaps < 0 "
                       "OR (games = 0 AND (snaps != 0 OR finish IS NOT NULL)) OR (games > 0 AND finish IS NULL)",
                       (MAX_GAMES,)).fetchone()[0]
    if bad:
        fails.append(f"{bad} player-years with implausible games/snaps/finish")
    bad = conn.execute("""SELECT COUNT(*) FROM mart_idp_prospect_outcome WHERE nfl_season != draft_season + year_index - 1
                          OR years_observed != (SELECT COUNT(*) FROM mart_idp_prospect_outcome o
                                                WHERE o.gsis_id = mart_idp_prospect_outcome.gsis_id)""").fetchone()[0]
    if bad:
        fails.append(f"{bad} rows whose season or years_observed disagrees with the draft year")
    # every group-season has players; a drafted player's finish is within his group's player count
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_outcome WHERE finish > group_players").fetchone()[0]
    if bad:
        fails.append(f"{bad} finishes beyond the group size")
    # right-censoring is explicit: the newest class (draft = last closed season) has exactly one observed year
    if closed:
        last = max(closed)
        newest = tuple(conn.execute("SELECT MIN(years_observed), MAX(years_observed) FROM mart_idp_prospect_outcome "
                                    "WHERE draft_season = ?", (last,)).fetchone())
        if newest != (1, 1):
            fails.append(f"class {last} years_observed {newest}, expected (1, 1)")
    return fails
