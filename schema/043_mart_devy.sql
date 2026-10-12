-- Phase 14 marts (apps read these only). Renaming from source names happens here, once (rule 3).
-- Counts are summed; rates are computed at read time from the counts (rule 4). CFBD has no birthdate: `age` is NULL.

-- PFF college id for a CFBD player: Turon's approval of data/devy_pff_review.csv (config/devy_pff_identity.csv). Owner: devy.identity.
CREATE TABLE devy_pff_identity (
  cfbd_id TEXT PRIMARY KEY,
  pff_id INTEGER,
  reason TEXT
);

CREATE VIEW mart_devy_cfbd_stats AS
SELECT season, playerId AS cfbd_id, MAX(player) AS name, GROUP_CONCAT(DISTINCT team) AS teams,
  SUM(CASE WHEN category = 'passing' AND statType = 'ATT' THEN stat END) AS pass_att,
  SUM(CASE WHEN category = 'passing' AND statType = 'COMPLETIONS' THEN stat END) AS pass_cmp,
  SUM(CASE WHEN category = 'passing' AND statType = 'YDS' THEN stat END) AS pass_yds,
  SUM(CASE WHEN category = 'passing' AND statType = 'TD' THEN stat END) AS pass_td,
  SUM(CASE WHEN category = 'passing' AND statType = 'INT' THEN stat END) AS pass_int,
  SUM(CASE WHEN category = 'rushing' AND statType = 'CAR' THEN stat END) AS rush_att,
  SUM(CASE WHEN category = 'rushing' AND statType = 'YDS' THEN stat END) AS rush_yds,
  SUM(CASE WHEN category = 'rushing' AND statType = 'TD' THEN stat END) AS rush_td,
  SUM(CASE WHEN category = 'receiving' AND statType = 'REC' THEN stat END) AS rec,
  SUM(CASE WHEN category = 'receiving' AND statType = 'YDS' THEN stat END) AS rec_yds,
  SUM(CASE WHEN category = 'receiving' AND statType = 'TD' THEN stat END) AS rec_td,
  SUM(CASE WHEN category = 'defensive' AND statType = 'TOT' THEN stat END) AS tackles,
  SUM(CASE WHEN category = 'defensive' AND statType = 'SOLO' THEN stat END) AS tackles_solo,
  SUM(CASE WHEN category = 'defensive' AND statType = 'TFL' THEN stat END) AS tackles_for_loss,
  SUM(CASE WHEN category = 'defensive' AND statType = 'SACKS' THEN stat END) AS sacks,
  SUM(CASE WHEN category = 'defensive' AND statType = 'QB HUR' THEN stat END) AS qb_hurries,
  SUM(CASE WHEN category = 'defensive' AND statType = 'PD' THEN stat END) AS pass_breakups,
  SUM(CASE WHEN category = 'interceptions' AND statType = 'INT' THEN stat END) AS def_int
FROM core_cfbd_player_season
GROUP BY season, playerId;

-- Bio: one row per (season, player). height inches, weight lb, class 1-4 (CFBD `year`); a player on two teams in a
-- season keeps the larger value of each field (the roster rows differ only by team).
CREATE VIEW mart_devy_bio AS
SELECT season, id AS cfbd_id, MAX(firstName || ' ' || lastName) AS name, GROUP_CONCAT(DISTINCT team) AS school,
  MAX(position) AS cfbd_position, MAX(height) AS height_in, MAX(weight) AS weight_lb, MAX(year) AS class_year,
  MAX(homeState) AS home_state, NULL AS age
FROM core_cfbd_roster
GROUP BY season, id;

CREATE VIEW mart_devy_usage AS
SELECT season, id AS cfbd_id, MAX(usage_overall) AS usage_overall, MAX(usage_pass) AS usage_pass,
       MAX(usage_rush) AS usage_rush, MAX(usage_thirdDown) AS usage_third_down
FROM core_cfbd_player_usage GROUP BY season, id;

-- PFF college, one row per (season, PFF player), every facet it appears in.
CREATE VIEW mart_devy_pff AS
WITH base AS (
  SELECT season, player_id FROM core_pff_ncaa_passing_season UNION
  SELECT season, player_id FROM core_pff_ncaa_rushing_season UNION
  SELECT season, player_id FROM core_pff_ncaa_receiving_season UNION
  SELECT season, player_id FROM core_pff_ncaa_defense_season UNION
  SELECT season, player_id FROM core_pff_ncaa_pass_rush_season)
SELECT b.season, b.player_id AS pff_id,
  COALESCE(pa.player, ru.player, re.player, de.player, pr.player) AS pff_name,
  COALESCE(pa.team_name, ru.team_name, re.team_name, de.team_name, pr.team_name) AS pff_team,
  MAX(COALESCE(pa.player_game_count, 0), COALESCE(ru.player_game_count, 0), COALESCE(re.player_game_count, 0),
      COALESCE(de.player_game_count, 0), COALESCE(pr.player_game_count, 0)) AS games,
  COALESCE(pa.eligible_season, ru.eligible_season, re.eligible_season, de.eligible_season, pr.eligible_season) AS draft_eligible_season,
  COALESCE(pa.draft_season, ru.draft_season, re.draft_season, de.draft_season, pr.draft_season) AS draft_season,
  pa.grades_pass AS pass_grade, pa.grades_offense AS pass_offense_grade, pa.btt_rate AS big_time_throw_rate,
  pa.twp_rate AS turnover_worthy_rate, pa.ypa AS pass_ypa_pff, pa.qb_rating,
  ru.grades_run AS run_grade, ru.yards_after_contact AS rush_yards_after_contact, ru.elusive_rating, ru.breakaway_percent,
  ru.targets AS rb_targets, ru.receptions AS rb_receptions, ru.rec_yards AS rb_rec_yards,
  re.grades_pass_route AS route_grade, re.targets AS wr_targets, re.receptions AS wr_receptions, re.yards AS wr_rec_yards,
  re.yprr, re.drop_rate, re.contested_catch_rate, re.slot_rate, re.wide_rate,
  de.grades_defense AS defense_grade, de.grades_coverage_defense AS coverage_grade, de.grades_run_defense AS run_defense_grade,
  de.grades_tackle AS tackle_grade, de.tackles AS pff_tackles, de.stops, de.missed_tackle_rate,
  pr.grades_pass_rush_defense AS pass_rush_grade, pr.total_pressures, pr.pass_rush_win_rate, pr.sacks AS pff_sacks
FROM base b
LEFT JOIN core_pff_ncaa_passing_season pa ON pa.season = b.season AND pa.player_id = b.player_id
LEFT JOIN core_pff_ncaa_rushing_season ru ON ru.season = b.season AND ru.player_id = b.player_id
LEFT JOIN core_pff_ncaa_receiving_season re ON re.season = b.season AND re.player_id = b.player_id
LEFT JOIN core_pff_ncaa_defense_season de ON de.season = b.season AND de.player_id = b.player_id
LEFT JOIN core_pff_ncaa_pass_rush_season pr ON pr.season = b.season AND pr.player_id = b.player_id;

-- Position group from CFBD's own position (the screenshot's position is only a label).
CREATE VIEW mart_devy_position_map AS
SELECT 'QB' AS pos, 'QB' AS grp UNION ALL SELECT 'RB', 'RB' UNION ALL SELECT 'FB', 'RB' UNION ALL SELECT 'WR', 'WR'
UNION ALL SELECT 'TE', 'TE' UNION ALL SELECT 'DL', 'DL' UNION ALL SELECT 'DE', 'DL' UNION ALL SELECT 'DT', 'DL'
UNION ALL SELECT 'EDGE', 'DL' UNION ALL SELECT 'NT', 'DL' UNION ALL SELECT 'LB', 'LB' UNION ALL SELECT 'DB', 'DB'
UNION ALL SELECT 'CB', 'DB' UNION ALL SELECT 'S', 'DB';

-- Everything per (season, CFBD player) the tracker shows: bio + CFBD stats + usage + PFF where Turon approved a link.
-- production_score is a RANKING AID, not a fantasy projection: QB 0.04/pass yd + 4/pass TD - 2/INT + 0.1/rush yd + 6/rush TD;
-- RB/WR/TE 0.1/yd + 6/TD + 0.5/rec; DL/LB/DB 1/tackle + 1.5/TFL + 4/sack + 4/INT + 1.5/PD + 1/hurry (season totals).
CREATE VIEW mart_devy_player_season AS
SELECT bio.season, bio.cfbd_id, bio.name, bio.school, bio.cfbd_position, pm.grp AS position_group,
  bio.height_in, bio.weight_lb, bio.class_year, bio.age, bio.home_state,
  COALESCE(pf.games, NULL) AS games, pf.draft_eligible_season, pf.draft_season,
  s.pass_att, s.pass_cmp, s.pass_yds, s.pass_td, s.pass_int,
  CASE WHEN s.pass_att > 0 THEN 100.0 * s.pass_cmp / s.pass_att END AS pass_cmp_pct,
  CASE WHEN s.pass_att > 0 THEN 1.0 * s.pass_yds / s.pass_att END AS pass_ypa,
  s.rush_att, s.rush_yds, s.rush_td, CASE WHEN s.rush_att > 0 THEN 1.0 * s.rush_yds / s.rush_att END AS rush_ypc,
  s.rec, s.rec_yds, s.rec_td, CASE WHEN s.rec > 0 THEN 1.0 * s.rec_yds / s.rec END AS rec_ypr,
  s.tackles, s.tackles_solo, s.tackles_for_loss, s.sacks, s.qb_hurries, s.pass_breakups, s.def_int,
  u.usage_overall, u.usage_pass, u.usage_rush,
  pf.pff_id, pf.pass_grade, pf.big_time_throw_rate, pf.turnover_worthy_rate, pf.run_grade, pf.rush_yards_after_contact,
  pf.elusive_rating, pf.route_grade, pf.wr_targets, pf.rb_targets, pf.yprr, pf.drop_rate,
  pf.defense_grade, pf.coverage_grade, pf.run_defense_grade, pf.pass_rush_grade, pf.total_pressures, pf.pass_rush_win_rate,
  CASE pm.grp
    WHEN 'QB' THEN 0.04 * COALESCE(s.pass_yds, 0) + 4 * COALESCE(s.pass_td, 0) - 2 * COALESCE(s.pass_int, 0)
                   + 0.1 * COALESCE(s.rush_yds, 0) + 6 * COALESCE(s.rush_td, 0)
    WHEN 'RB' THEN 0.1 * (COALESCE(s.rush_yds, 0) + COALESCE(s.rec_yds, 0)) + 6 * (COALESCE(s.rush_td, 0) + COALESCE(s.rec_td, 0))
                   + 0.5 * COALESCE(s.rec, 0)
    WHEN 'WR' THEN 0.1 * (COALESCE(s.rush_yds, 0) + COALESCE(s.rec_yds, 0)) + 6 * (COALESCE(s.rush_td, 0) + COALESCE(s.rec_td, 0))
                   + 0.5 * COALESCE(s.rec, 0)
    WHEN 'TE' THEN 0.1 * (COALESCE(s.rush_yds, 0) + COALESCE(s.rec_yds, 0)) + 6 * (COALESCE(s.rush_td, 0) + COALESCE(s.rec_td, 0))
                   + 0.5 * COALESCE(s.rec, 0)
    ELSE COALESCE(s.tackles, 0) + 1.5 * COALESCE(s.tackles_for_loss, 0) + 4 * COALESCE(s.sacks, 0) + 4 * COALESCE(s.def_int, 0)
         + 1.5 * COALESCE(s.pass_breakups, 0) + COALESCE(s.qb_hurries, 0)
  END AS production_score
FROM mart_devy_bio bio
JOIN mart_devy_position_map pm ON pm.pos = bio.cfbd_position
LEFT JOIN mart_devy_cfbd_stats s ON s.season = bio.season AND s.cfbd_id = bio.cfbd_id
LEFT JOIN mart_devy_usage u ON u.season = bio.season AND u.cfbd_id = bio.cfbd_id
LEFT JOIN devy_pff_identity pi ON pi.cfbd_id = bio.cfbd_id
LEFT JOIN mart_devy_pff pf ON pf.season = bio.season AND pf.pff_id = pi.pff_id;

-- The tracker board: one row per roster cell per season. `is_mine` comes from my_franchises (the config), never a name.
-- A cell Turon marked "skip" (no CFBD id) keeps its row with NULL stats so the roster still shows it.
CREATE VIEW mart_devy_board AS
SELECT d.league_id, ml.name AS league_name, d.franchise_id, d.franchise_name,
  CASE WHEN mf.my_franchise = d.franchise_id THEN 1 ELSE 0 END AS is_mine,
  d.line, d.devy_slot, d.source_text, d.position AS position_written, d.school_text, d.seen_on, i.cfbd_id, i.reason AS mapping_reason,
  ps.season, ps.name, ps.school, ps.cfbd_position, ps.position_group, ps.height_in, ps.weight_lb, ps.class_year, ps.age,
  ps.games, ps.draft_eligible_season, ps.draft_season,
  ps.pass_att, ps.pass_cmp, ps.pass_yds, ps.pass_td, ps.pass_int, ps.pass_cmp_pct, ps.pass_ypa,
  ps.rush_att, ps.rush_yds, ps.rush_td, ps.rush_ypc, ps.rec, ps.rec_yds, ps.rec_td, ps.rec_ypr,
  ps.tackles, ps.tackles_solo, ps.tackles_for_loss, ps.sacks, ps.qb_hurries, ps.pass_breakups, ps.def_int,
  ps.usage_overall, ps.pff_id, ps.pass_grade, ps.big_time_throw_rate, ps.turnover_worthy_rate, ps.run_grade,
  ps.rush_yards_after_contact, ps.elusive_rating, ps.route_grade, ps.yprr, ps.drop_rate, ps.defense_grade, ps.coverage_grade,
  ps.run_defense_grade, ps.pass_rush_grade, ps.total_pressures, ps.production_score
FROM app_devy_roster d
LEFT JOIN devy_identity i ON i.source_text = d.source_text AND i.position = d.position AND i.school_text = d.school_text
LEFT JOIN my_franchises mf ON mf.platform = 'mfl' AND mf.league_id = d.league_id AND mf.season = 2026
LEFT JOIN my_franchises ml ON ml.platform = 'mfl' AND ml.league_id = d.league_id AND ml.season = 2026
LEFT JOIN mart_devy_player_season ps ON ps.cfbd_id = i.cfbd_id;

-- Free agents: FBS players NOT on any roster cell in that league, for each of the four devy leagues.
CREATE VIEW mart_devy_free_agents AS
SELECT l.league_id, ps.*
FROM (SELECT DISTINCT league_id FROM app_devy_roster) l
JOIN mart_devy_player_season ps
LEFT JOIN (SELECT DISTINCT d.league_id, i.cfbd_id FROM app_devy_roster d
           JOIN devy_identity i ON i.source_text = d.source_text AND i.position = d.position AND i.school_text = d.school_text
           WHERE i.cfbd_id IS NOT NULL) owned ON owned.league_id = l.league_id AND owned.cfbd_id = ps.cfbd_id
WHERE owned.cfbd_id IS NULL AND ps.season >= 2025 AND ps.production_score > 0
  AND ps.school IN (SELECT DISTINCT team FROM core_cfbd_player_season WHERE conference IN
       ('Big Ten', 'ACC', 'SEC', 'Big 12', 'American Athletic', 'Mid-American', 'Sun Belt', 'Mountain West', 'Conference USA',
        'Pac-12', 'FBS Independents'));
