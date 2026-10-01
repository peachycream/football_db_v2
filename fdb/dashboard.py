"""Player Dashboard marts (REBUILD_DESIGN §6, Phase 7a): builder `dashboard.build`.

    mart_player_week          player-week stats + snaps + inside-20 targets
    mart_qb_dropback_week     QB dropback sums        (v1 ingest_qb_pass_zones_v1, same filters)
    mart_qb_pass_zones_week   QB zone sums            (v1 ingest_qb_pass_zones_v1)
    mart_rb_run_lanes_week    RB lane sums            (v1 ingest_rb_run_lanes_v1)
    mart_player_routes_week   route tree: routes / targets / catches / yards per route type
                              (FTN participation, 2026-; v1's FPD route file has no successor)
    mart_player_targets_by_route_week   2016-2025 history: TARGETS by the targeted receiver's
                              route (nflverse participation); no routes-run denominator exists

All four are rebuilt wholly from core in one transaction (delete, insert, check, commit or
roll back). Every season_type is built; the app reads REG, as v1 did. Differences from v1:
  * snaps are joined by exact pfr id -> gsis (player_ids), not v1's name slugs.
  * inside-20 targets come from nflverse pbp for every season. v1 read FPD (retired) and
    then FTN charts with a throwaway flag (`qbta`) that v2's FTN feed does not carry.
  * lane yards use pbp `yards_gained` (v1 read `rushing_yards`, which core_pbp does not
    carry; the two differ only on laterals).
"""

_SNAPS = """
    SELECT sc.season, sc.season_type, sc.week, p.gsis_id,
           SUM(sc.offense_snaps) AS offense_snaps,
           SUM(sc.offense_pct * sc.offense_snaps) / NULLIF(SUM(sc.offense_snaps), 0) AS offense_pct,
           SUM(sc.defense_snaps) AS defense_snaps,
           SUM(sc.defense_pct * sc.defense_snaps) / NULLIF(SUM(sc.defense_snaps), 0) AS defense_pct,
           GROUP_CONCAT(DISTINCT sc.team) AS snap_teams, COUNT(DISTINCT sc.team) AS n_snap_teams,
           MAX(sc.team) AS team, MAX(sc.position) AS position
    FROM core_snap_counts sc
    JOIN player_ids p ON p.source = 'pfr' AND p.source_id = sc.pfr_player_id
    GROUP BY sc.season, sc.season_type, sc.week, p.gsis_id"""

_RZ = """
    SELECT season, season_type, week, receiver_player_id AS gsis_id, COUNT(*) AS rz_targets
    FROM core_pbp
    WHERE yardline_100 <= 20 AND pass_attempt = 1 AND two_point_attempt = 0 AND receiver_player_id IS NOT NULL
    GROUP BY season, season_type, week, receiver_player_id"""

PLAYER_WEEK = f"""
INSERT INTO mart_player_week
WITH snaps AS MATERIALIZED ({_SNAPS}),
     rz AS MATERIALIZED ({_RZ}),
     keys AS (SELECT season, season_type, week, player_id AS gsis_id FROM core_player_stats WHERE player_id IS NOT NULL
              UNION SELECT season, season_type, week, gsis_id FROM snaps)
SELECT k.season, k.season_type, k.week, k.gsis_id,
       COALESCE(s.team, n.team), COALESCE(s.position, n.position),
       s.attempts, s.completions, s.passing_yards, s.passing_tds, s.passing_interceptions,
       s.carries, s.rushing_yards, s.targets, s.receptions, s.receiving_yards,
       s.target_share, s.air_yards_share, s.wopr, s.fantasy_points_ppr,
       r.rz_targets,
       n.offense_snaps, n.offense_pct, n.defense_snaps, n.defense_pct, n.snap_teams, n.n_snap_teams
FROM keys k
LEFT JOIN core_player_stats s ON s.player_id = k.gsis_id AND s.season = k.season
                             AND s.season_type = k.season_type AND s.week = k.week
LEFT JOIN snaps n ON n.gsis_id = k.gsis_id AND n.season = k.season AND n.season_type = k.season_type AND n.week = k.week
LEFT JOIN rz r ON r.gsis_id = k.gsis_id AND r.season = k.season AND r.season_type = k.season_type AND r.week = k.week"""

QB_DROPBACK = """
INSERT INTO mart_qb_dropback_week
SELECT season, season_type, week, passer_player_id,
       COUNT(*), COALESCE(SUM(epa), 0), COALESCE(SUM(success), 0),
       SUM(pass_attempt = 1), SUM(pass_attempt = 1 AND complete_pass = 1),
       SUM(pass_attempt = 1 AND cp IS NOT NULL), COALESCE(SUM(CASE WHEN pass_attempt = 1 THEN cp END), 0)
FROM core_pbp
WHERE qb_dropback = 1 AND two_point_attempt = 0 AND passer_player_id IS NOT NULL
GROUP BY season, season_type, week, passer_player_id"""

QB_ZONES = """
INSERT INTO mart_qb_pass_zones_week
SELECT season, season_type, week, passer_player_id, pass_location,
       CASE WHEN air_yards < 0 THEN 'blos' WHEN air_yards < 10 THEN 'short' WHEN air_yards < 20 THEN 'medium' ELSE 'deep' END,
       COUNT(*), COALESCE(SUM(complete_pass), 0), SUM(cp IS NOT NULL), COALESCE(SUM(cp), 0),
       COALESCE(SUM(epa), 0), COALESCE(SUM(success), 0), SUM(air_yards)
FROM core_pbp
WHERE pass_attempt = 1 AND two_point_attempt = 0 AND pass_location IS NOT NULL AND air_yards IS NOT NULL
  AND passer_player_id IS NOT NULL
GROUP BY 1, 2, 3, 4, 5, 6"""

RB_LANES = """
INSERT INTO mart_rb_run_lanes_week
SELECT season, season_type, week, rusher_player_id, lane,
       COUNT(*), COALESCE(SUM(yards_gained), 0), COALESCE(SUM(epa), 0), COALESCE(SUM(success), 0)
FROM (SELECT *, CASE WHEN run_location = 'middle' THEN 'M'
                     WHEN run_location IN ('left', 'right') AND run_gap IN ('end', 'tackle', 'guard')
                     THEN (CASE run_location WHEN 'left' THEN 'L' ELSE 'R' END)
                          || (CASE run_gap WHEN 'end' THEN 'E' WHEN 'tackle' THEN 'T' ELSE 'G' END) END AS lane
      FROM core_pbp
      WHERE rush_attempt = 1 AND two_point_attempt = 0 AND qb_scramble = 0 AND rusher_player_id IS NOT NULL)
WHERE lane IS NOT NULL
GROUP BY 1, 2, 3, 4, 5"""

_SLOTS = " UNION ALL ".join(
    f"SELECT x.season, x.season_type, x.week, x.pid, x.skp{i} AS gsis_id, x.route{i} AS route FROM core_ftn_participation x "
    f"WHERE x.skp{i} IS NOT NULL AND x.route{i} IS NOT NULL" for i in range(1, 6))

PLAYER_ROUTES = f"""
INSERT INTO mart_player_routes_week
SELECT r.season, r.season_type, r.week, r.gsis_id, r.route,
       COUNT(*), SUM(CASE WHEN p.trg = r.gsis_id THEN 1 ELSE 0 END),
       SUM(CASE WHEN p.trg = r.gsis_id AND p.comp = 1 THEN 1 ELSE 0 END),
       COALESCE(SUM(CASE WHEN p.trg = r.gsis_id AND p.comp = 1 THEN p.yds END), 0)
FROM ({_SLOTS}) r
JOIN core_ftn_plays p ON p.pid = r.pid AND p.type IN ('PASS', 'RUSH')   -- RUSH: scrambles etc.; no-plays excluded
GROUP BY 1, 2, 3, 4, 5"""

TARGETS_BY_ROUTE = """
INSERT INTO mart_player_targets_by_route_week
SELECT b.season, b.season_type, b.week, b.receiver_player_id, x.route,
       COUNT(*), SUM(CASE WHEN b.complete_pass = 1 THEN 1 ELSE 0 END),
       COALESCE(SUM(CASE WHEN b.complete_pass = 1 THEN b.yards_gained END), 0)
FROM core_participation x
JOIN core_pbp b ON b.game_id = x.nflverse_game_id AND b.play_id = x.play_id
WHERE x.route IS NOT NULL AND b.pass_attempt = 1 AND b.two_point_attempt = 0 AND b.receiver_player_id IS NOT NULL
GROUP BY 1, 2, 3, 4, 5"""

TABLES = ("mart_player_week", "mart_qb_dropback_week", "mart_qb_pass_zones_week", "mart_rb_run_lanes_week",
          "mart_player_routes_week", "mart_player_targets_by_route_week")


def checks(conn) -> list[str]:
    fails = []
    # every nflverse stat line is present, and no row was invented
    # (nflverse ships ~21 nameless all-zero team rows a season, player_id NULL: not player lines)
    n_stats = conn.execute("SELECT COUNT(*) FROM core_player_stats WHERE player_id IS NOT NULL").fetchone()[0]
    n_with = conn.execute("SELECT COUNT(*) FROM mart_player_week WHERE pass_attempts IS NOT NULL OR carries IS NOT NULL "
                          "OR targets IS NOT NULL OR fantasy_points_ppr IS NOT NULL").fetchone()[0]
    if n_with != n_stats:
        fails.append(f"mart_player_week has {n_with} stat rows, core_player_stats {n_stats}")
    for s, st, a, b in conn.execute("""
            SELECT m.season, m.season_type, m.t, c.t FROM
              (SELECT season, season_type, SUM(targets) t FROM mart_player_week GROUP BY 1, 2) m
              JOIN (SELECT season, season_type, SUM(targets) t FROM core_player_stats GROUP BY 1, 2) c
                ON c.season = m.season AND c.season_type = m.season_type WHERE m.t IS NOT c.t"""):
        fails.append(f"{s} {st}: targets {a} vs core {b}")
    # snaps resolve: >= 99% of snap-count rows reach a gsis id (exact pfr keys only)
    for s, n, hit in conn.execute("""
            SELECT sc.season, COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM core_snap_counts sc
            LEFT JOIN player_ids p ON p.source = 'pfr' AND p.source_id = sc.pfr_player_id GROUP BY 1"""):
        if hit < 0.99 * n:
            fails.append(f"{s}: only {hit}/{n} snap rows resolve to gsis")
    # zones: located attempts are 97-100% of nflverse passing attempts (REG); lanes cover >= 90% of designed runs
    for s, z, a in conn.execute("""
            SELECT z.season, z.a, c.a FROM (SELECT season, SUM(attempts) a FROM mart_qb_pass_zones_week
                                             WHERE season_type = 'REG' GROUP BY 1) z
            JOIN (SELECT season, SUM(attempts) a FROM core_player_stats WHERE season_type = 'REG' GROUP BY 1) c
              ON c.season = z.season"""):
        if not 0.97 * a <= z <= 1.0 * a:
            fails.append(f"{s}: zone attempts {z} vs nflverse attempts {a}")
    for s, lanes, runs in conn.execute("""
            SELECT l.season, l.c, r.c FROM (SELECT season, SUM(carries) c FROM mart_rb_run_lanes_week GROUP BY 1) l
            JOIN (SELECT season, COUNT(*) c FROM core_pbp WHERE rush_attempt = 1 AND two_point_attempt = 0
                  AND qb_scramble = 0 AND rusher_player_id IS NOT NULL GROUP BY 1) r ON r.season = l.season"""):
        if lanes < 0.90 * runs:
            fails.append(f"{s}: lanes hold {lanes}/{runs} designed runs")
    # route targets agree with nflverse targets for every route-charted week (FTN vs nflverse, within 2%)
    for s, st, w, a, b in conn.execute("""
            SELECT r.season, r.season_type, r.week, r.t, n.t FROM
              (SELECT season, season_type, week, SUM(targets) t FROM mart_player_routes_week GROUP BY 1, 2, 3) r
              JOIN (SELECT season, season_type, week, SUM(targets) t FROM core_player_stats GROUP BY 1, 2, 3) n
                ON n.season = r.season AND n.season_type = r.season_type AND n.week = r.week"""):
        if not 0.95 * b <= a <= 1.02 * b:
            fails.append(f"{s} {st}{w}: route-tree targets {a} vs nflverse {b}")
    # targets-by-route history: route-tagged targets are 97-100.5% of nflverse's targets every season
    for s, a, b in conn.execute("""
            SELECT r.season, r.t, n.t FROM
              (SELECT season, SUM(targets) t FROM mart_player_targets_by_route_week GROUP BY 1) r
              JOIN (SELECT season, SUM(targets) t FROM core_player_stats GROUP BY 1) n ON n.season = r.season"""):
        if not 0.97 * b <= a <= 1.005 * b:
            fails.append(f"{s}: targets-by-route {a} vs nflverse targets {b}")
    bad = conn.execute("SELECT COUNT(*) FROM mart_qb_dropback_week WHERE completions > attempts OR attempts > dropbacks "
                       "OR cpoe_attempts > attempts").fetchone()[0]
    if bad:
        fails.append(f"{bad} dropback rows with completions > attempts > dropbacks broken")
    return fails


def build(conn) -> dict:
    conn.execute("BEGIN")
    try:
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
        for sql in (PLAYER_WEEK, QB_DROPBACK, QB_ZONES, RB_LANES, PLAYER_ROUTES, TARGETS_BY_ROUTE):
            conn.execute(sql)
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        fails = checks(conn)
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"failures": fails, "summary": ", ".join(f"{t.replace('mart_', '')} {n}" for t, n in counts.items())}
