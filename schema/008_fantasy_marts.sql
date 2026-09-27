-- Ownership marts (REBUILD_DESIGN §6). Apps read these, never core_*.
-- Renaming happens here, once.

-- config/my_franchises.toml as a table, so marts can join it. Owner: fantasy.config
-- (a builder: rebuilt from the checked-in file on every build).
CREATE TABLE my_franchises (
  platform      TEXT NOT NULL,
  league_id     TEXT NOT NULL,
  season        INTEGER NOT NULL,
  name          TEXT NOT NULL,
  my_franchise  TEXT NOT NULL,
  PRIMARY KEY (platform, league_id, season)
);

-- One row per roster slot in the LATEST snapshot of every (season, league).
-- pool = MFL's own playerLimitUnit: LEAGUE (one pool), CONFERENCE, or DIVISION;
-- pool_capacity = rostersPerPlayer (owners a player may have within one pool).
-- Sleeper leagues are one pool with capacity 1.
-- player_key: gsis_id when identity resolves it; otherwise a key naming the source
-- id. MFL ids 0800-0999 are LEAGUE-SCOPED custom (devy) players - the same id is a
-- different person in each league - so an unresolved MFL key includes the league.
CREATE VIEW mart_roster_ownership AS
WITH mfl_latest AS (
  SELECT season, league_id, MAX(snapshot_at) AS snapshot_at FROM core_mfl_rosters GROUP BY season, league_id
), slp_latest AS (
  SELECT season, league_id, MAX(snapshot_at) AS snapshot_at FROM core_sleeper_rosters GROUP BY season, league_id
)
SELECT 'mfl' AS platform, r.season, r.league_id, l.name AS league_name,
       l.playerLimitUnit AS pool_unit,
       CASE l.playerLimitUnit WHEN 'CONFERENCE' THEN d.conference WHEN 'DIVISION' THEN f.division ELSE '' END AS pool_id,
       CASE l.playerLimitUnit WHEN 'CONFERENCE' THEN c.name WHEN 'DIVISION' THEN d.name ELSE '' END AS pool_name,
       l.rostersPerPlayer AS pool_capacity,
       r.franchise_id, f.name AS franchise_name, f.owner_name,
       CASE WHEN r.franchise_id = m.my_franchise THEN 1 ELSE 0 END AS is_mine,
       r.id AS source_player_id, pi.gsis_id,
       COALESCE(pi.gsis_id, 'mfl:' || r.league_id || ':' || r.id) AS player_key,
       r.status AS roster_status,
       CASE r.status WHEN 'TAXI_SQUAD' THEN 'taxi' WHEN 'INJURED_RESERVE' THEN 'ir' ELSE 'roster' END AS slot,
       r.snapshot_at
FROM core_mfl_rosters r
JOIN mfl_latest x ON x.season = r.season AND x.league_id = r.league_id AND x.snapshot_at = r.snapshot_at
JOIN core_mfl_league l ON l.season = r.season AND l.league_id = r.league_id
JOIN core_mfl_franchises f ON f.season = r.season AND f.league_id = r.league_id AND f.id = r.franchise_id
LEFT JOIN core_mfl_divisions d ON d.season = f.season AND d.league_id = f.league_id AND d.id = f.division
LEFT JOIN core_mfl_conferences c ON c.season = d.season AND c.league_id = d.league_id AND c.id = d.conference
LEFT JOIN my_franchises m ON m.platform = 'mfl' AND m.league_id = r.league_id AND m.season = r.season
LEFT JOIN player_ids pi ON pi.source = 'mfl' AND pi.source_id = r.id
UNION ALL
SELECT 'sleeper', r.season, r.league_id, l.name,
       'LEAGUE', '', '', 1,
       CAST(r.roster_id AS TEXT),
       COALESCE(NULLIF(json_extract(u.metadata, '$.team_name'), ''), u.display_name, 'Roster ' || r.roster_id),
       u.display_name,
       CASE WHEN CAST(r.roster_id AS TEXT) = m.my_franchise THEN 1 ELSE 0 END,
       r.player_id, pi.gsis_id,
       COALESCE(pi.gsis_id, 'sleeper:' || r.player_id),
       NULL,
       CASE WHEN r.in_reserve THEN 'ir' WHEN r.in_taxi THEN 'taxi' WHEN r.in_starters THEN 'starter' ELSE 'bench' END,
       r.snapshot_at
FROM core_sleeper_rosters r
JOIN slp_latest x ON x.season = r.season AND x.league_id = r.league_id AND x.snapshot_at = r.snapshot_at
JOIN core_sleeper_league l ON l.season = r.season AND l.league_id = r.league_id
LEFT JOIN core_sleeper_users u ON u.season = r.season AND u.league_id = r.league_id AND u.user_id = r.owner_id
LEFT JOIN my_franchises m ON m.platform = 'sleeper' AND m.league_id = r.league_id AND m.season = r.season
LEFT JOIN player_ids pi ON pi.source = 'sleeper' AND pi.source_id = r.player_id;

-- Every roster slot whose player has no gsis_id, WITH ITS REASON. The Phase 3 gate:
-- 0 silently dropped roster ids. `category` separates what is expected today
-- (devy: CFB is a later phase) from what is actionable (an NFL player unmapped).
CREATE VIEW mart_roster_unresolved AS
SELECT o.platform, o.season, o.league_id, o.league_name, o.franchise_id, o.franchise_name,
       o.source_player_id, o.player_key, o.slot,
       COALESCE(mp.name, sp.full_name) AS source_name,
       COALESCE(mp.position, sp.position) AS source_position,
       COALESCE(mp.team, sp.team) AS source_team,
       CASE
         WHEN q.reason IS NOT NULL THEN 'quarantined'
         WHEN o.platform = 'mfl' AND mp.id IS NULL THEN 'unknown_id'
         WHEN o.platform = 'mfl' AND mp.draft_year IS NULL AND mp.team = 'FA' THEN 'devy'
         WHEN o.platform = 'sleeper' AND sp.player_id IS NULL THEN 'unknown_id'
         ELSE 'nfl_unmapped'
       END AS category,
       CASE
         WHEN q.reason IS NOT NULL THEN 'quarantined: ' || q.reason
         WHEN o.platform = 'mfl' AND mp.id IS NULL THEN 'id is not in this league''s MFL player list'
         WHEN o.platform = 'mfl' AND mp.draft_year IS NULL AND mp.team = 'FA'
           THEN 'league-custom MFL player with no NFL draft year or team (devy/college; CFB is a later phase)'
         WHEN o.platform = 'sleeper' AND sp.player_id IS NULL THEN 'id is not in Sleeper /players/nfl'
         WHEN o.platform = 'sleeper' THEN 'Sleeper has no gsis_id, and no cross-id bridge meets the bar (2 agreeing ids, or 1 + exact birth date)'
         ELSE 'NFL player with no mfl -> gsis mapping (DynastyProcess has none)'
       END AS reason
FROM mart_roster_ownership o
LEFT JOIN core_mfl_players mp ON o.platform = 'mfl' AND mp.season = o.season AND mp.league_id = o.league_id AND mp.id = o.source_player_id
LEFT JOIN core_sleeper_players sp ON o.platform = 'sleeper' AND sp.player_id = o.source_player_id
LEFT JOIN (SELECT source, source_id, MIN(reason) AS reason FROM identity_quarantine GROUP BY source, source_id) q
       ON q.source = o.platform AND q.source_id = o.source_player_id
WHERE o.gsis_id IS NULL;

-- The ownership search universe: every NFL person (players) plus every unresolved
-- rostered player under its source key, with a display name, position and team.
-- n_leagues = distinct leagues rostering the player in the latest season.
CREATE VIEW mart_player_search AS
WITH cur AS (SELECT MAX(season) AS season FROM mart_roster_ownership),
held AS (
  SELECT player_key, COUNT(DISTINCT platform || ':' || league_id) AS n_leagues
  FROM mart_roster_ownership WHERE season = (SELECT season FROM cur) GROUP BY player_key
)
SELECT p.gsis_id AS player_key, p.gsis_id, p.display_name AS name, p.position, p.position_group,
       p.latest_team AS team, COALESCE(h.n_leagues, 0) AS n_leagues, 0 AS is_devy
FROM players p LEFT JOIN held h ON h.player_key = p.gsis_id
UNION ALL
SELECT u.player_key, NULL,
       CASE WHEN instr(u.source_name, ', ') > 0 AND u.platform = 'mfl'
            THEN substr(u.source_name, instr(u.source_name, ', ') + 2) || ' ' || substr(u.source_name, 1, instr(u.source_name, ', ') - 1)
            ELSE COALESCE(u.source_name, u.source_player_id) END,
       u.source_position, NULL, u.source_team, COUNT(DISTINCT u.platform || ':' || u.league_id),
       MAX(u.category = 'devy')
FROM mart_roster_unresolved u
WHERE u.season = (SELECT season FROM cur)
GROUP BY u.player_key;
