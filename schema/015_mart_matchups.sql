-- Matchups marts (REBUILD_DESIGN §6, Phase 6). Renaming happens here, once.
--
-- v1's team_pos_fp_allowed_weekly stored RAW SUMS per (allowing team, week, group).
-- v2 keeps PLAYER-GAME rows instead: MFL scores per player-game with bonuses
-- ("5/300" = 5 points per full 300 yards), which a team-week sum cannot reproduce.
-- Scoring is applied at read time (app/matchups.py); nothing here is a rate or a point.

-- Every scheduled team-game, both sides, canonical team codes.
CREATE VIEW mart_team_week_opponent AS
SELECT s.season, s.season_type, s.week, s.game_id, h.team AS team, a.team AS opponent, 1 AS is_home,
       s.home_score AS team_score, s.away_score AS opp_score, s.result
FROM core_schedule s
JOIN team_aliases h ON h.abbr = s.home_team AND s.season BETWEEN h.season_from AND h.season_to
JOIN team_aliases a ON a.abbr = s.away_team AND s.season BETWEEN a.season_from AND a.season_to
UNION ALL
SELECT s.season, s.season_type, s.week, s.game_id, a.team, h.team, 0,
       s.away_score, s.home_score, s.result
FROM core_schedule s
JOIN team_aliases h ON h.abbr = s.home_team AND s.season BETWEEN h.season_from AND h.season_to
JOIN team_aliases a ON a.abbr = s.away_team AND s.season BETWEEN a.season_from AND a.season_to;

-- One row per player-game of production, keyed to the team that ALLOWED it.
--   off  QB/RB/WR/TE  core_player_stats (nflverse), position of that week (FB -> RB)
--   def  DT/DE/LB/CB/S core_pff_defense_week, PFF position DI -> DT, ED -> DE
--   st   PK           core_pff_fg_week, position K
CREATE VIEW mart_player_allowed_week AS
SELECT s.season, s.season_type, s.week, 'off' AS side,
       CASE s.position WHEN 'FB' THEN 'RB' ELSE s.position END AS position_group,
       t.team, o.team AS allowing_team,
       s.player_id AS player_key, s.player_id AS gsis_id, s.player_display_name AS name,
       s.attempts AS pass_attempts, s.completions, s.passing_yards AS pass_yards, s.passing_tds AS pass_tds,
       s.passing_interceptions AS interceptions, s.sacks_suffered AS sacks, s.sack_yards_lost AS sack_yards,
       s.carries, s.rushing_yards AS rush_yards, s.rushing_tds AS rush_tds, s.targets, s.receptions,
       s.receiving_yards AS rec_yards, s.receiving_tds AS rec_tds,
       s.rushing_fumbles AS fumbles, s.fumbles_lost_total AS fumbles_lost, s.fumbles_total,
       s.passing_2pt_conversions AS passing_2pt, s.rushing_2pt_conversions AS rushing_2pt,
       s.receiving_2pt_conversions AS receiving_2pt, s.passing_first_downs, s.rushing_first_downs,
       s.receiving_first_downs, s.special_teams_tds,
       s.kickoff_return_yards AS kr_yards, s.punt_return_yards AS pr_yards,
       -- an offensive player's own defensive/special-teams stats (MFL's catch-all tackle
       -- rules name QB/RB/WR/TE too): nflverse credits them on the same player row
       s.def_tackles_solo AS def_tackles, s.def_tackle_assists AS def_assists, NULL AS def_tfl, NULL AS def_sacks,
       NULL AS def_qb_hits, NULL AS def_pass_breakups, NULL AS def_batted_passes, NULL AS def_interceptions,
       NULL AS def_int_tds, s.def_fumbles_forced AS def_forced_fumbles, NULL AS def_fumble_recoveries,
       NULL AS def_fr_tds, NULL AS def_safeties, NULL AS def_tds, NULL AS def_stops, NULL AS def_pressures, NULL AS def_snaps,
       NULL AS def_cov_targets, NULL AS def_cov_receptions, NULL AS def_cov_yards,
       NULL AS fg_made_0_19, NULL AS fg_made_20_29, NULL AS fg_made_30_39, NULL AS fg_made_40_49, NULL AS fg_made_50p,
       NULL AS fg_att_0_19, NULL AS fg_att_20_29, NULL AS fg_att_30_39, NULL AS fg_att_40_49, NULL AS fg_att_50p,
       NULL AS fg_made_total, NULL AS fg_att_total, NULL AS pat_made, NULL AS pat_att
FROM core_player_stats s
JOIN team_aliases t ON t.abbr = s.team AND s.season BETWEEN t.season_from AND t.season_to
JOIN team_aliases o ON o.abbr = s.opponent_team AND s.season BETWEEN o.season_from AND o.season_to
WHERE s.position IN ('QB', 'RB', 'FB', 'WR', 'TE')
UNION ALL
SELECT d.season, d.season_type, d.week, 'def',
       CASE d.position WHEN 'DI' THEN 'DT' WHEN 'ED' THEN 'DE' ELSE d.position END,
       t.team, x.opponent,
       'pff:' || d.player_id, pi.gsis_id, d.player,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       d.tackles, d.assists, d.tackles_for_loss, d.sacks, d.hits,
       d.pass_break_ups, d.batted_passes, d.interceptions, d.interception_touchdowns,
       d.forced_fumbles, d.fumble_recoveries, d.fumble_recovery_touchdowns, d.safeties,
       d.touchdowns, d.stops, d.total_pressures, d.snap_counts_defense,
       d.targets, d.receptions, d.yards,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
FROM core_pff_defense_week d
JOIN team_aliases t ON t.abbr = d.team_name AND d.season BETWEEN t.season_from AND t.season_to
JOIN mart_team_week_opponent x ON x.season = d.season AND x.season_type = d.season_type AND x.week = d.week AND x.team = t.team
LEFT JOIN player_ids pi ON pi.source = 'pff' AND pi.source_id = CAST(d.player_id AS TEXT)
WHERE d.position IN ('DI', 'ED', 'LB', 'CB', 'S')
UNION ALL
SELECT k.season, k.season_type, k.week, 'st', 'PK',
       t.team, x.opponent,
       'pff:' || k.player_id, pi.gsis_id, k.player,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, NULL, NULL, NULL,
       k.one_made, k.twenty_made, k.thirty_made, k.forty_made, k.fifty_made,
       k.one_attempts, k.twenty_attempts, k.thirty_attempts, k.forty_attempts, k.fifty_attempts,
       k.total_made, k.total_attempts, k.pat_made, k.pat_attempts
FROM core_pff_fg_week k
JOIN team_aliases t ON t.abbr = k.team_name AND k.season BETWEEN t.season_from AND t.season_to
JOIN mart_team_week_opponent x ON x.season = k.season AND x.season_type = k.season_type AND x.week = k.week AND x.team = t.team
LEFT JOIN player_ids pi ON pi.source = 'pff' AND pi.source_id = CAST(k.player_id AS TEXT)
WHERE k.position = 'K';

-- MFL scoring rules as the apps read them (latest season per league).
CREATE VIEW mart_mfl_rules AS
SELECT r.league_id, r.season, r.positions, r.event, r."range", r.points
FROM core_mfl_rules r
JOIN (SELECT league_id, MAX(season) s FROM core_mfl_rules GROUP BY league_id) m
  ON m.league_id = r.league_id AND m.s = r.season;

-- MFL reported points per player-week, with the exact-key chain mfl -> gsis -> pff:
-- the IDP calibration truth (REBUILD_DESIGN §6: empirical factor, applied at read time).
CREATE VIEW mart_mfl_reported_week AS
SELECT sc.season, sc.season_type, sc.week, sc.league_id, sc.id AS mfl_id, sc.score,
       pm.gsis_id, pp.source_id AS pff_id
FROM core_mfl_player_scores sc
LEFT JOIN player_ids pm ON pm.source = 'mfl' AND pm.source_id = sc.id
LEFT JOIN player_ids pp ON pp.source = 'pff' AND pp.gsis_id = pm.gsis_id;

CREATE VIEW mart_mfl_leagues AS
SELECT l.league_id, l.name, l.season FROM core_mfl_league l
JOIN (SELECT league_id, MAX(season) s FROM core_mfl_league GROUP BY league_id) m ON m.league_id = l.league_id AND m.s = l.season;
