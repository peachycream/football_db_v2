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


# ---- Phase 15d: pre-draft features -> mart_idp_prospect_features (builder `idp_prospect.features`) -------------------------
FEATURE_FIRST_DRAFT = 2017   # the feature season is the season before the draft; PFF NCAA is loaded from 2016
FEATURE_FIRST_COLLEGE = 2016
# Errata (Phase 15d, found 2026-10-31): the 2026 draft table gives Peter Woods (Clemson DT, pick 29) the gsis_id WOO547869, which
# players.csv holds for a different person (rookie 1980, born 1955, Missouri). The id is exact but wrong. A drafted player whose
# players row has a rookie_season BEFORE the draft is an identity conflict: the players-derived fields are dropped (not guessed),
# only the draft-table and combine facts are kept. Any conflict outside this set fails the build.
ID_CONFLICT_ERRATA = {("WOO547869", 2026)}
MIN_COLLEGE_COVERAGE = 0.90  # per closed draft class: drafted defenders with a PFF NCAA row in some season <= draft - 1 (15a: 97.6-99%)
P5 = {"Southeastern Conference", "Big Ten Conference", "Atlantic Coast Conference", "Pacific Twelve Conference",
      "Big Twelve Conference"}
G5 = {"American Athletic Conference", "Mid-American Conference", "Mountain West Conference", "Conference USA",
      "Sun Belt Conference", "Independent"}
DEF_FINAL = {  # feature column -> core_pff_ncaa_defense_season column
    "c_games": "player_game_count", "c_snaps_defense": "snap_counts_defense", "c_snaps_run_defense": "snap_counts_run_defense",
    "c_snaps_coverage": "snap_counts_coverage", "c_snaps_pass_rush": "snap_counts_pass_rush", "c_snaps_box": "snap_counts_box",
    "c_snaps_slot": "snap_counts_slot", "c_snaps_dl": "snap_counts_dl", "c_snaps_offball": "snap_counts_offball",
    "c_snaps_corner": "snap_counts_corner", "c_snaps_fs": "snap_counts_fs", "c_tackles": "tackles", "c_assists": "assists",
    "c_missed_tackles": "missed_tackles", "c_tfl": "tackles_for_loss", "c_stops": "stops", "c_sacks": "sacks", "c_hits": "hits",
    "c_hurries": "hurries", "c_pressures": "total_pressures", "c_pass_break_ups": "pass_break_ups",
    "c_interceptions": "interceptions", "c_forced_fumbles": "forced_fumbles", "c_targets": "targets",
    "c_receptions": "receptions", "c_cov_yards": "yards", "c_grade_defense": "grades_defense",
    "c_grade_run_defense": "grades_run_defense", "c_grade_coverage": "grades_coverage_defense",
    "c_grade_pass_rush": "grades_pass_rush_defense", "c_grade_tackle": "grades_tackle"}
PR_FINAL = {"pr_opp": "pass_rush_opp", "pr_wins": "pass_rush_wins", "pr_snaps": "snap_counts_pass_rush",
            "pr_pressures": "total_pressures", "pr_true_opp": "true_pass_set_pass_rush_opp",
            "pr_true_wins": "true_pass_set_pass_rush_wins", "pr_true_snaps": "true_pass_set_snap_counts_pass_rush",
            "pr_grade": "grades_pass_rush_defense"}
CAREER = {"k_games": "player_game_count", "k_snaps_defense": "snap_counts_defense", "k_tackles": "tackles",
          "k_tfl": "tackles_for_loss", "k_sacks": "sacks", "k_pressures": "total_pressures"}


def _inches(ht):
    try:
        f, i = str(ht).split("-")
        return int(f) * 12 + int(i)
    except (ValueError, AttributeError):
        return None


def _age(birth, on):
    """Years between an ISO birth date and a date (YYYY-MM-DD), two decimals; None if either is missing."""
    from datetime import date
    try:
        b = date.fromisoformat(birth)
        d = date.fromisoformat(on)
    except (TypeError, ValueError):
        return None
    return round((d - b).days / 365.25, 2)


def _tier(conf):
    if not conf or conf == "NO COLLEGE":
        return None
    return "P5" if conf in P5 else "G5" if conf in G5 else "OTHER"


def _rows_by_player(conn, table):
    out = defaultdict(dict)
    for r in conn.execute(f"SELECT * FROM {table}"):
        if r["season"] in out[r["player_id"]]:
            raise ValueError(f"{table}: two rows for player {r['player_id']} in {r['season']}")
        out[r["player_id"]][r["season"]] = r
    return out


def build_features(conn) -> dict:
    if not conn.execute("SELECT 1 FROM core_nflverse_draft_picks LIMIT 1").fetchone():
        conn.execute("DELETE FROM mart_idp_prospect_features")
        return {"failures": [], "summary": "no draft picks loaded"}
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mart_idp_prospect_features)")]
    closed = _closed_seasons(conn)
    last_closed = max(closed) if closed else None
    pop = conn.execute("""SELECT d.gsis_id, d.season, d.round, d.pick, d.position, d.pfr_player_id, p.pff_id, p.pff_position,
                                 p.birth_date, p.height, p.college_name, p.college_conference, p.rookie_season
                          FROM core_nflverse_draft_picks d LEFT JOIN core_nflverse_players p ON p.gsis_id = d.gsis_id
                          WHERE d.side = 'D' AND d.season >= ? AND d.gsis_id IS NOT NULL ORDER BY d.season, d.pick""",
                       (FEATURE_FIRST_DRAFT,)).fetchall()
    skipped = conn.execute("SELECT COUNT(*) FROM core_nflverse_draft_picks WHERE side = 'D' AND season >= ? AND gsis_id IS NULL",
                           (FEATURE_FIRST_DRAFT,)).fetchone()[0]
    combine = {}
    for r in conn.execute("SELECT * FROM core_nflverse_combine WHERE pfr_id IS NOT NULL AND season = draft_year"):
        combine.setdefault((r["pfr_id"], r["season"]), r)
    dfn, prs = _rows_by_player(conn, "core_pff_ncaa_defense_season"), _rows_by_player(conn, "core_pff_ncaa_pass_rush_season")

    out, conflicts = [], []
    for gsis, season, rnd, pick, pos, pfr, pff, pff_pos, birth, p_height, college, conf, rook in pop:
        row = dict.fromkeys(cols)
        cmb = combine.get((pfr, season))
        h = _inches(cmb["ht"]) if cmb else None
        row.update(gsis_id=gsis, pff_id=pff, draft_season=season, draft_round=rnd, draft_pick=pick, draft_position=pos,
                   nfl_pff_position=pff_pos, age_at_draft=_age(birth, f"{season}-04-25"),
                   height_in=h if h is not None else (int(p_height) if p_height else None),
                   height_source="combine" if h is not None else ("players" if p_height else None),
                   weight_lb=cmb["wt"] if cmb else None, has_combine=int(cmb is not None),
                   has_forty=int(bool(cmb and cmb["forty"] is not None)), college_name=college, college_conference=conf,
                   conference_tier=_tier(conf))
        if cmb:
            for k in ("forty", "bench", "vertical", "broad_jump", "cone", "shuttle"):
                row[k] = cmb[k]
        if rook is not None and rook < season:   # the players row is somebody else
            conflicts.append((gsis, season))
            row.update(pff_id=None, nfl_pff_position=None, age_at_draft=None, college_name=None, college_conference=None,
                       conference_tier=None, height_in=h, height_source="combine" if h is not None else None)
            pff = None
        pid = int(pff) if pff and str(pff).isdigit() else None
        seasons = sorted(s for s in dfn.get(pid, {}) if s <= season - 1) if pid is not None else []
        row["has_college"] = int(bool(seasons))
        row["has_pass_rush"] = 0
        if seasons:
            fs = seasons[-1]
            d = dfn[pid][fs]
            row.update(college_season=fs, college_season_gap=season - 1 - fs, college_seasons=len(seasons),
                       first_college_season=seasons[0], left_censored=int(seasons[0] == FEATURE_FIRST_COLLEGE),
                       age_at_college_season=_age(birth, f"{fs}-09-01"), college_position=d["position"])
            for k, c in DEF_FINAL.items():
                row[k] = d[c]
            pr = prs.get(pid, {}).get(fs)
            if pr is not None:
                row["has_pass_rush"] = 1
                for k, c in PR_FINAL.items():
                    row[k] = pr[c]
            for k, c in CAREER.items():
                row[k] = sum((dfn[pid][s][c] or 0) for s in seasons)
            row["k_pr_opp"] = sum((prs[pid][s]["pass_rush_opp"] or 0) for s in seasons if s in prs.get(pid, {}))
            row["k_pr_wins"] = sum((prs[pid][s]["pass_rush_wins"] or 0) for s in seasons if s in prs.get(pid, {}))
        out.append(tuple(row[c] for c in cols))

    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM mart_idp_prospect_features")
        conn.executemany(f"INSERT INTO mart_idp_prospect_features ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", out)
        fails = feature_checks(conn, len(pop), last_closed)
        fails += [f"{g} ({s}): players row predates the draft, not in ID_CONFLICT_ERRATA" for g, s in conflicts if (g, s) not in ID_CONFLICT_ERRATA]
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    n_col = sum(1 for r in out if r[cols.index("has_college")])
    n_cmb = sum(1 for r in out if r[cols.index("has_combine")])
    return {"failures": fails, "summary": f"{len(out)} drafted defenders {FEATURE_FIRST_DRAFT}+ ({skipped} without gsis_id skipped), "
                                          f"{n_col} with college rows, {n_cmb} with a combine row, {len(conflicts)} id conflict(s) {sorted(conflicts)}"}


def feature_checks(conn, n_players, last_closed) -> list[str]:
    fails = []
    n = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_features").fetchone()[0]
    if n != n_players:
        fails.append(f"{n} rows, {n_players} drafted defenders expected")
    # no leakage: nothing is dated after the season before the draft, and the combine matched the draft year by construction
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_features WHERE college_season > draft_season - 1 "
                       "OR college_season_gap < 0 OR first_college_season > college_season").fetchone()[0]
    if bad:
        fails.append(f"{bad} rows with a college season after the season before the draft")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_features WHERE (has_college = 0 AND college_season IS NOT NULL) "
                       "OR (has_college = 1 AND college_season IS NULL) OR (has_forty = 1 AND forty IS NULL) "
                       "OR (has_combine = 0 AND (forty IS NOT NULL OR weight_lb IS NOT NULL))").fetchone()[0]
    if bad:
        fails.append(f"{bad} rows whose indicator disagrees with its data")
    bad = conn.execute("SELECT gsis_id, draft_season, c_games, k_games, age_at_draft, height_in FROM mart_idp_prospect_features "
                       "WHERE c_games > 17 OR k_games < c_games OR age_at_draft NOT BETWEEN 19 AND 30 "
                       "OR height_in NOT BETWEEN 60 AND 85").fetchall()
    if bad:
        fails.append(f"{len(bad)} rows with implausible games, age or height, e.g. {[tuple(r) for r in bad[:3]]}")
    for s, n, c in conn.execute("SELECT draft_season, COUNT(*), SUM(has_college) FROM mart_idp_prospect_features "
                                "GROUP BY draft_season ORDER BY 1"):
        if last_closed and s <= last_closed and c < MIN_COLLEGE_COVERAGE * n:
            fails.append(f"class {s}: only {c}/{n} drafted defenders reach a college row")
    return fails
