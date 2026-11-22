-- Flex-position analysis inputs (analysis/flex_position/build.py). Views only, no new table, no loader.
-- MFL's `starters` JSON has no explicit flex slot: a position's "limit" is min-max and the league's
-- count / idp_starters / iop_starters give the total. Flex slots = total - sum(min), per side.
-- Players are owned per POOL (league, conference or division) and rostersPerPlayer owners may hold one player, so the
-- teams competing for the supply = pool_teams / rosters_per_player.
-- Counts only (games, points); PPG is computed at read time.

CREATE VIEW mart_mfl_position_slots AS
SELECT l.league_id, l.season,
       json_extract(p.value, '$.name') AS position,
       CAST(CASE WHEN instr(json_extract(p.value, '$.limit'), '-') > 0
                 THEN substr(json_extract(p.value, '$.limit'), 1, instr(json_extract(p.value, '$.limit'), '-') - 1)
                 ELSE json_extract(p.value, '$.limit') END AS INTEGER) AS min_slots,
       CAST(CASE WHEN instr(json_extract(p.value, '$.limit'), '-') > 0
                 THEN substr(json_extract(p.value, '$.limit'), instr(json_extract(p.value, '$.limit'), '-') + 1)
                 ELSE json_extract(p.value, '$.limit') END AS INTEGER) AS max_slots
FROM core_mfl_league l, json_each(l.starters, '$.position') p
JOIN (SELECT league_id, MAX(season) s FROM core_mfl_league GROUP BY league_id) m
  ON m.league_id = l.league_id AND m.s = l.season;

CREATE VIEW mart_mfl_lineup_size AS
SELECT l.league_id, l.season, l.name,
       (SELECT COUNT(*) FROM core_mfl_franchises f WHERE f.season = l.season AND f.league_id = l.league_id) AS teams,
       l.playerLimitUnit AS pool_unit, l.rostersPerPlayer AS rosters_per_player,
       -- teams that compete for one player pool (core_mfl_league.playerLimitUnit), then / rostersPerPlayer
       CASE l.playerLimitUnit
         WHEN 'DIVISION' THEN (SELECT MAX(n) FROM (SELECT COUNT(*) n FROM core_mfl_franchises f
                                WHERE f.season = l.season AND f.league_id = l.league_id GROUP BY f.division))
         WHEN 'CONFERENCE' THEN (SELECT MAX(n) FROM (SELECT COUNT(*) n FROM core_mfl_franchises f
                                JOIN core_mfl_divisions d ON d.season = f.season AND d.league_id = f.league_id AND d.id = f.division
                                WHERE f.season = l.season AND f.league_id = l.league_id GROUP BY d.conference))
         ELSE (SELECT COUNT(*) FROM core_mfl_franchises f WHERE f.season = l.season AND f.league_id = l.league_id)
       END AS pool_teams,
       CAST(json_extract(l.starters, '$.count') AS INTEGER) AS total_starters,
       CAST(json_extract(l.starters, '$.idp_starters') AS INTEGER) AS idp_starters,
       CAST(COALESCE(json_extract(l.starters, '$.iop_starters'),
                     json_extract(l.starters, '$.count') - json_extract(l.starters, '$.idp_starters')) AS INTEGER) AS off_starters
FROM core_mfl_league l
JOIN (SELECT league_id, MAX(season) s FROM core_mfl_league GROUP BY league_id) m
  ON m.league_id = l.league_id AND m.s = l.season;

-- Season to date, regular season, MFL's own reported points. A played game = a non-zero score row
-- (MFL writes 0.0 for players with no game). Position is MFL's own for that id (no name matching).
CREATE VIEW mart_mfl_player_games AS
SELECT s.season, s.league_id, s.id AS mfl_id, p.position,
       SUM(s.score <> 0) AS games, SUM(s.score) AS points,
       MAX(s.week) AS through_week
FROM core_mfl_player_scores s
JOIN core_mfl_players p ON p.season = s.season AND p.league_id = s.league_id AND p.id = s.id
JOIN (SELECT league_id, MAX(season) ms FROM core_mfl_player_scores GROUP BY league_id) m
  ON m.league_id = s.league_id AND m.ms = s.season
WHERE s.season_type = 'REG'
GROUP BY s.season, s.league_id, s.id, p.position;
