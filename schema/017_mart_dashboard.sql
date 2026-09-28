-- Player Dashboard marts (REBUILD_DESIGN §6, Phase 7a). Tables are built by `dashboard.build`
-- (fdb/dashboard.py) from core only; views rename source columns once, here (rule 3).
-- Everything is a COUNT or a SUM: every rate is computed at read time (rule 4).

-- One row per player-week: nflverse stats + snap counts (pfr id -> gsis by player_ids) +
-- inside-20 targets from pbp. A player with snaps but no stat line still has a row
-- (a blocking TE's game counts as a game played).
CREATE TABLE mart_player_week (
  season            INTEGER NOT NULL,
  season_type       TEXT    NOT NULL,
  week              INTEGER NOT NULL,
  gsis_id           TEXT    NOT NULL,
  team              TEXT,
  position          TEXT,               -- nflverse's position that week (stats row, else snap row)
  pass_attempts     INTEGER, completions INTEGER, pass_yards REAL, pass_tds INTEGER, interceptions INTEGER,
  carries           INTEGER, rush_yards REAL,
  targets           INTEGER, receptions INTEGER, rec_yards REAL,
  target_share      REAL,               -- nflverse, 0-1, per game (weighted at read time)
  air_yards_share   REAL,               -- nflverse, 0-1
  wopr              REAL,
  fantasy_points_ppr REAL,
  rz_targets        INTEGER,            -- pbp: yardline_100 <= 20, pass attempt, not a 2-pt try
  offense_snaps     INTEGER, offense_pct REAL,   -- pct 0-1, snap-weighted across a split week
  defense_snaps     INTEGER, defense_pct REAL,
  snap_teams        TEXT,               -- comma list when a player logged snaps for 2 teams in a week
  n_snap_teams      INTEGER,
  PRIMARY KEY (season, season_type, week, gsis_id)
);
CREATE INDEX ix_mart_player_week_player ON mart_player_week(gsis_id, season);

-- QB dropbacks per passer-week (v1 ingest_qb_pass_zones_v1 build_dropback_rows, exact filters):
-- qb_dropback = 1 AND two_point_attempt = 0; attempts/completions/cp within those rows.
CREATE TABLE mart_qb_dropback_week (
  season INTEGER NOT NULL, season_type TEXT NOT NULL, week INTEGER NOT NULL, gsis_id TEXT NOT NULL,
  dropbacks INTEGER NOT NULL, sum_epa REAL NOT NULL, successes INTEGER NOT NULL,
  attempts INTEGER NOT NULL, completions INTEGER NOT NULL, cpoe_attempts INTEGER NOT NULL, sum_cp REAL NOT NULL,
  PRIMARY KEY (season, season_type, week, gsis_id)
);

-- QB pass zones (v1 build_zone_rows): pass_attempt = 1, not 2-pt, located, air_yards known.
-- depth: air_yards < 0 blos, < 10 short, < 20 medium, else deep.
CREATE TABLE mart_qb_pass_zones_week (
  season INTEGER NOT NULL, season_type TEXT NOT NULL, week INTEGER NOT NULL, gsis_id TEXT NOT NULL,
  zone_direction TEXT NOT NULL, zone_depth TEXT NOT NULL,
  attempts INTEGER NOT NULL, completions INTEGER NOT NULL, cpoe_attempts INTEGER NOT NULL,
  sum_cp REAL NOT NULL, sum_epa REAL NOT NULL, successes INTEGER NOT NULL, air_yards_sum REAL NOT NULL,
  PRIMARY KEY (season, season_type, week, gsis_id, zone_direction, zone_depth)
);

-- RB run lanes (v1 ingest_rb_run_lanes_v1): rush_attempt = 1, not 2-pt, not a scramble;
-- middle -> M; left/right x end/tackle/guard -> LE LT LG RG RT RE; anything else has no lane.
CREATE TABLE mart_rb_run_lanes_week (
  season INTEGER NOT NULL, season_type TEXT NOT NULL, week INTEGER NOT NULL, gsis_id TEXT NOT NULL,
  lane TEXT NOT NULL, carries INTEGER NOT NULL, yards_sum REAL NOT NULL, sum_epa REAL NOT NULL, successes INTEGER NOT NULL,
  PRIMARY KEY (season, season_type, week, gsis_id, lane)
);

-- PFF offense season line (REG+POST, the week-list call) keyed to gsis by exact PFF id.
CREATE VIEW mart_pff_offense_season AS
SELECT o.season, p.gsis_id, o.player_id AS pff_id, o.position AS pff_position, o.player_game_count AS games,
       o.grades_offense, o.grades_pass, o.grades_run, o.grades_pass_route,
       o.snap_counts_pass_route AS routes, o.snap_counts_pass AS pass_snaps
FROM core_pff_offense_season o
LEFT JOIN player_ids p ON p.source = 'pff' AND p.source_id = CAST(o.player_id AS TEXT);

-- PFF dropbacks per QB-season (same REG+POST scope as the season grades): the QB tile pool.
CREATE VIEW mart_pff_qb_dropbacks_season AS
SELECT x.season, p.gsis_id, SUM(x.dropbacks) AS dropbacks
FROM core_pff_passing_week x
JOIN player_ids p ON p.source = 'pff' AND p.source_id = CAST(x.player_id AS TEXT)
GROUP BY x.season, p.gsis_id;

-- PFF defense season line: alignment/role snaps, counts, grades. position_group from PFF's
-- own position that season (DI -> DT, ED -> DE), not a single "current" label.
CREATE VIEW mart_pff_defense_season AS
SELECT d.season, p.gsis_id, d.player_id AS pff_id, d.position AS pff_position,
       CASE d.position WHEN 'DI' THEN 'DT' WHEN 'ED' THEN 'DE' ELSE d.position END AS position_group,
       d.player_game_count AS games, d.snap_counts_defense AS snaps_total,
       d.snap_counts_dl AS snaps_dl, d.snap_counts_box AS snaps_box, d.snap_counts_slot AS snaps_slot,
       d.snap_counts_corner AS snaps_corner, d.snap_counts_fs AS snaps_fs,
       d.snap_counts_run_defense AS snaps_run_defense, d.snap_counts_pass_rush AS snaps_pass_rush,
       d.snap_counts_coverage AS snaps_coverage,
       d.tackles, d.assists, d.tackles_for_loss, d.sacks, d.hits, d.interceptions, d.pass_break_ups,
       d.forced_fumbles, d.fumble_recoveries, d.missed_tackles, d.missed_tackle_rate, d.total_pressures,
       d.yards AS yards_allowed,
       d.grades_defense AS grade_defense, d.grades_run_defense AS grade_run_defense,
       d.grades_pass_rush_defense AS grade_pass_rush, d.grades_coverage_defense AS grade_coverage
FROM core_pff_defense_season d
LEFT JOIN player_ids p ON p.source = 'pff' AND p.source_id = CAST(d.player_id AS TEXT);

-- ffverse expected fantasy points per player-week (player_id is a gsis id at source).
-- season_type from the game's own type in the schedule (17-week seasons end at week 17).
CREATE VIEW mart_ff_opportunity_week AS
SELECT o.season, CASE WHEN s.game_type = 'REG' THEN 'REG' ELSE 'POST' END AS season_type, o.week,
       o.player_id AS gsis_id, o.total_fantasy_points_exp, o.rec_fantasy_points_exp
FROM core_ff_opportunity o
JOIN core_schedule s ON s.game_id = o.game_id;

-- MFL-reported fantasy points per player-week and league, by exact mfl id -> gsis.
CREATE VIEW mart_player_league_points_week AS
SELECT sc.season, sc.season_type, sc.week, sc.league_id, pm.gsis_id, sc.score
FROM core_mfl_player_scores sc
JOIN player_ids pm ON pm.source = 'mfl' AND pm.source_id = sc.id;

-- Profile fields for the header.
CREATE VIEW mart_player_profile AS
SELECT gsis_id, display_name AS full_name, position, latest_team AS team, birth_date, draft_year
FROM players;

-- NGS passing per QB-week: CPOE is a rate, so it is weighted by attempts at read time.
CREATE VIEW mart_ngs_passing_week AS
SELECT season, season_type, week, player_gsis_id AS gsis_id, attempts,
       completion_percentage_above_expectation AS cpoe
FROM core_ngs_passing WHERE week > 0;

-- PFF weekly receiving / rushing counts keyed to gsis (REG-only season sums are possible).
CREATE VIEW mart_pff_receiving_week AS
SELECT x.season, x.season_type, x.week, p.gsis_id, x.routes
FROM core_pff_receiving_week x
JOIN player_ids p ON p.source = 'pff' AND p.source_id = CAST(x.player_id AS TEXT);

CREATE VIEW mart_pff_rushing_week AS
SELECT x.season, x.season_type, x.week, p.gsis_id, x.attempts, x.avoided_tackles, x.yards_after_contact,
       x.explosive, x.breakaway_yards, x.yards
FROM core_pff_rushing_week x
JOIN player_ids p ON p.source = 'pff' AND p.source_id = CAST(x.player_id AS TEXT);
