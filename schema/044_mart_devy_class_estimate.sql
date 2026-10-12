-- Phase 14: a draft-class ESTIMATE for players PFF has no link for (free agents, and any rostered player Turon did not link).
-- draft_class_est = season + max(1, 4 - CFBD class year): a freshman (1) in 2026 -> 2029, a junior (3) -> 2027, a senior (4) or later -> 2027.
-- It ignores redshirts and early declarations, is NULL when PFF has the player's own draft class, and is always shown labelled as an estimate.
DROP VIEW mart_devy_free_agents;
DROP VIEW mart_devy_board;
DROP VIEW mart_devy_player_season;

-- Everything per (season, CFBD player) the tracker shows: bio + CFBD stats + usage + PFF where Turon approved a link.
-- production_score is a RANKING AID, not a fantasy projection: QB 0.04/pass yd + 4/pass TD - 2/INT + 0.1/rush yd + 6/rush TD;
-- RB/WR/TE 0.1/yd + 6/TD + 0.5/rec; DL/LB/DB 1/tackle + 1.5/TFL + 4/sack + 4/INT + 1.5/PD + 1/hurry (season totals).
CREATE VIEW mart_devy_player_season AS
SELECT bio.season, bio.cfbd_id, bio.name, bio.school, bio.cfbd_position, pm.grp AS position_group,
  bio.height_in, bio.weight_lb, bio.class_year, bio.age, bio.home_state,
  pf.games AS games, pf.draft_eligible_season, pf.draft_season,
  CASE WHEN pf.draft_eligible_season IS NULL AND pf.draft_season IS NULL AND bio.class_year IS NOT NULL
       THEN bio.season + MAX(1, 4 - bio.class_year) END AS draft_class_est,
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
  ps.games, ps.draft_eligible_season, ps.draft_season, ps.draft_class_est,
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
