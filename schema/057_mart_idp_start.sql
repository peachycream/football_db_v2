-- IDP start/sit analysis inputs (fdb/idp_start.py, app/idp_start.py). Views only: no table, no loader.
-- Counts only (rule 4): points per category are computed at read time from the league's MFL rules.
-- No name matching (rule 1): every join below is on a source-native id or on player_ids by exact key
-- (nflverse stats and PFR snaps on gsis_id; PFF -> gsis by exact PFF id; MFL id -> gsis by exact MFL id).
--
-- Source choice is measured, not assumed (REBUILD_LOG "IDP start/sit"): scoring PFF's stat lines reproduced MFL's
-- reported player-week in 28% (30590) / 36% (46276) of rows; nflverse's defender stats reproduce 92% / 81%. So the
-- counts MFL scores come from nflverse (core_player_stats); PFF supplies only what nflverse lacks:
-- fumble recoveries and the two return-TD counts.

-- One row per defender-week (REG, 2025+): a player with a defensive snap. NULL stat columns = no nflverse stat row
-- (read as 0 by the builder, which first checks that each week has nflverse defender rows at all).
-- defense_pct is 0-1 (the player's defensive snaps / the team's), from PFR snap counts.
CREATE VIEW mart_idp_week AS
SELECT w.season, w.week, w.gsis_id, w.team, w.position AS nfl_position,
       s.def_tackles_solo AS tackles, s.def_tackle_assists AS assists, s.def_tackles_for_loss AS tfl,
       s.def_sacks AS sacks, s.def_qb_hits AS qb_hits, s.def_pass_defended AS pass_breakups,
       s.def_interceptions AS interceptions, s.def_fumbles_forced AS forced_fumbles, s.def_safeties AS safeties,
       p.fumble_recoveries, p.int_tds, p.fr_tds,
       (s.player_id IS NOT NULL) AS has_stat_row,
       w.defense_snaps, w.defense_pct
FROM mart_player_week w
LEFT JOIN core_player_stats s ON s.season = w.season AND s.season_type = w.season_type
                             AND s.week = w.week AND s.player_id = w.gsis_id
LEFT JOIN (SELECT d.season, d.season_type, d.week, pi.gsis_id,
                  SUM(d.fumble_recoveries) AS fumble_recoveries,
                  SUM(d.interception_touchdowns) AS int_tds,
                  SUM(d.fumble_recovery_touchdowns) AS fr_tds
           FROM core_pff_defense_week d
           JOIN player_ids pi ON pi.source = 'pff' AND pi.source_id = CAST(d.player_id AS TEXT)
           GROUP BY d.season, d.season_type, d.week, pi.gsis_id) p
       ON p.season = w.season AND p.season_type = w.season_type AND p.week = w.week AND p.gsis_id = w.gsis_id
WHERE w.season_type = 'REG' AND w.season >= 2025 AND w.defense_snaps > 0;

-- A league's IDP-eligible players: MFL's own id, name and position for that league, mapped by exact MFL id.
CREATE VIEW mart_idp_league_player AS
SELECT p.season, p.league_id, p.id AS mfl_id, pi.gsis_id, p.name, p.position AS mfl_position, p.team
FROM core_mfl_players p
JOIN player_ids pi ON pi.source = 'mfl' AND pi.source_id = p.id
WHERE p.position IN ('DT', 'DE', 'LB', 'CB', 'S');
