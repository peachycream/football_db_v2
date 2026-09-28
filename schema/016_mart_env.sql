-- Team environment marts (Phase 6). Built by fdb/env.py (builder env.build) from core_pbp,
-- mart_participation_personnel, core_nflverse_ftn_charting, core_participation and the PFF tables.
-- SUMS ONLY: every rate is computed at read time (SUM(num)/SUM(den); hard rule 4). Canonical team
-- codes (team_aliases.team). All season types are built; the apps read REG, as v1 did.
-- NULL = no source for that input (PFF before its coverage, FTN 4-man in 2026): never 0.

CREATE TABLE mart_team_off_env_week (
  season INTEGER NOT NULL, season_type TEXT NOT NULL, week INTEGER NOT NULL,
  team TEXT NOT NULL, split TEXT NOT NULL,
  plays INTEGER,
  dropbacks INTEGER,
  pass_att INTEGER,
  rush_att INTEGER,
  sacks INTEGER,
  epa_sum REAL,
  success_sum INTEGER,
  cpoe_sum REAL,
  cpoe_n INTEGER,
  xpass_sum REAL,
  xpass_n INTEGER,
  air_yards_sum REAL,
  explosive_rush INTEGER,
  explosive_pass INTEGER,
  pa_plays INTEGER,
  pa_epa_sum REAL,
  screen_plays INTEGER,
  screen_epa_sum REAL,
  pace_sec_sum REAL,
  pace_snap_n INTEGER,
  no_huddle_plays INTEGER,
  drives INTEGER,
  drive_scores INTEGER,
  points INTEGER,
  third_down_att INTEGER,
  third_down_conv INTEGER,
  early_down_plays INTEGER,
  early_down_pass INTEGER,
  rz_trips INTEGER,
  rz_td INTEGER,
  PRIMARY KEY (season, season_type, week, team, split)
);
CREATE INDEX ix_mart_team_off_env ON mart_team_off_env_week(season, season_type, split, week);

CREATE TABLE mart_team_def_env_week (
  season INTEGER NOT NULL, season_type TEXT NOT NULL, week INTEGER NOT NULL,
  team TEXT NOT NULL,
  def_plays INTEGER,
  dropbacks_faced INTEGER,
  rush_att_faced INTEGER,
  neutral_plays_faced INTEGER,
  neutral_seconds_faced REAL,
  points_allowed INTEGER,
  drives_faced INTEGER,
  epa_sum_allowed REAL,
  success_ct_allowed INTEGER,
  explosive_ct_allowed INTEGER,
  pass_epa_sum_allowed REAL,
  rush_epa_sum_allowed REAL,
  early_epa_sum REAL,
  early_plays INTEGER,
  late_epa_sum REAL,
  late_plays INTEGER,
  cpoe_x_dropbacks REAL,
  comp_allowed INTEGER,
  att_allowed INTEGER,
  cov_yards_allowed INTEGER,
  cov_td_allowed INTEGER,
  cov_int INTEGER,
  air_yards_allowed_sum REAL,
  yac_allowed_sum REAL,
  deep_targets_allowed INTEGER,
  pass_rush_snaps INTEGER,
  pressures INTEGER,
  sacks INTEGER,
  hurries INTEGER,
  qb_hits INTEGER,
  rush_yards_allowed INTEGER,
  yco_allowed_sum REAL,
  stuffs INTEGER,
  third_down_faced INTEGER,
  third_down_conv_allowed INTEGER,
  rz_trips_faced INTEGER,
  rz_td_allowed INTEGER,
  three_and_out_forced INTEGER,
  proe_x_plays_faced REAL,
  tfl INTEGER,
  forced_fumbles INTEGER,
  pass_breakups INTEGER,
  havoc_plays INTEGER,
  run_def_grade_x_snaps REAL,
  tackle_grade_x_snaps REAL,
  tackle_grade_snaps INTEGER,
  pressures_4man_ftn INTEGER,
  pass_rush_plays_4man_ftn INTEGER,
  PRIMARY KEY (season, season_type, week, team)
);

-- source 'ftn_participation' (nflverse participation, as v1 named it) or 'pff' (PFF coverage scheme).
CREATE TABLE mart_team_def_scheme_week (
  season INTEGER NOT NULL, season_type TEXT NOT NULL, week INTEGER NOT NULL,
  team TEXT NOT NULL, source TEXT NOT NULL,
  man_snaps INTEGER,
  zone_snaps INTEGER,
  cover0_snaps INTEGER,
  cover1_snaps INTEGER,
  cover2_snaps INTEGER,
  cover3_snaps INTEGER,
  cover4_snaps INTEGER,
  cover6_snaps INTEGER,
  other_coverage_snaps INTEGER,
  base_snaps INTEGER,
  nickel_snaps INTEGER,
  dime_snaps INTEGER,
  other_pers_snaps INTEGER,
  blitz_dropbacks INTEGER,
  dropbacks_faced INTEGER,
  lightbox_rush_att INTEGER,
  lightbox_rush_yards INTEGER,
  heavybox_rush_att INTEGER,
  heavybox_rush_yards INTEGER,
  epa_vs_man_sum REAL,
  plays_vs_man INTEGER,
  epa_vs_zone_sum REAL,
  plays_vs_zone INTEGER,
  pff_man_targets INTEGER,
  pff_man_receptions INTEGER,
  pff_man_yards INTEGER,
  pff_man_coverage_snaps INTEGER,
  pff_zone_targets INTEGER,
  pff_zone_receptions INTEGER,
  pff_zone_yards INTEGER,
  pff_zone_coverage_snaps INTEGER,
  PRIMARY KEY (season, season_type, week, team, source)
);

-- Season defensive grades per team: PFF's REG+POST server-aggregated line, snap-weighted
-- (SUM(grade * snaps) / SUM(snaps) at read time). A player is counted for his season-line team.
CREATE VIEW mart_team_def_grades_season AS
SELECT x.season, a.team,
       SUM(x.grades_defense * x.snap_counts_defense) AS def_grade_x_snaps,
       SUM(x.grades_pass_rush_defense * x.snap_counts_defense) AS pass_rush_grade_x_snaps,
       SUM(x.grades_coverage_defense * x.snap_counts_defense) AS coverage_grade_x_snaps,
       SUM(x.snap_counts_defense) AS snaps
FROM core_pff_defense_season x
JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
WHERE x.snap_counts_defense > 0
GROUP BY x.season, a.team;

-- Offensive line pass-block grade per team-season (T/G/C), PFF REG+POST season line.
CREATE VIEW mart_team_pass_block_season AS
SELECT x.season, a.team, SUM(x.grades_pass_block * x.snap_counts_pass_block) AS grade_x_snaps,
       SUM(x.snap_counts_pass_block) AS snaps
FROM core_pff_offense_season x
JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
WHERE x.position IN ('T', 'G', 'C') AND x.grades_pass_block IS NOT NULL AND x.snap_counts_pass_block > 0
GROUP BY x.season, a.team;

-- Pressure allowed per team-week: PFF passing def_gen_pressures over dropbacks (REG+POST rows).
CREATE VIEW mart_team_pressure_allowed_week AS
SELECT x.season, x.season_type, x.week, a.team, SUM(x.def_gen_pressures) AS pressures, SUM(x.dropbacks) AS dropbacks
FROM core_pff_passing_week x
JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
WHERE x.dropbacks > 0
GROUP BY x.season, x.season_type, x.week, a.team;

-- Targets by receiver position per team-week (nflverse player_stats, that week's position).
CREATE VIEW mart_team_targets_week AS
SELECT s.season, s.season_type, s.week, a.team,
       CASE WHEN s.position IN ('RB', 'HB', 'FB') THEN 'RB' WHEN s.position IN ('WR', 'TE') THEN s.position ELSE 'other' END AS bucket,
       SUM(s.targets) AS targets
FROM core_player_stats s
JOIN team_aliases a ON a.abbr = s.team AND s.season BETWEEN a.season_from AND a.season_to
GROUP BY 1, 2, 3, 4, 5;
