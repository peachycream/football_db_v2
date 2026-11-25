-- Defense target-zone map inputs (fdb/def_zones.py, app/def_zones.py). Views only: no table, no loader.
-- Counts only (rule 4): rates, completion % and league ratios are computed at read time.
-- No name matching (rule 1): every join is on a source-native id (FTN pid; the targeted player's gsis id; team by
-- team_aliases exact spelling).
--
-- Source: FTN plays (core_ftn_plays). One owner for the whole map: lane/depth bucket (`loc`), depth of target (`dot`,
-- the air yards), the targeted player (`trg`), completion, yards, touchdown, and (from FTN participation) the targeted
-- receiver's charted route. Checked against nflverse pbp, 2026 REG wk 1-11: completions 6,867 = 6,867; air yards 81,778
-- vs 81,780; FTN counts 55 more targets than nflverse (plays without a lane are excluded here).
-- FTN charts routes from 2026 only, so the page is a 2026 view; route is NULL where the play has no route charting.

-- One row per target (a charted PASS play with an identified target and a lane), REG only.
CREATE VIEW mart_def_target_play AS
SELECT p.season, p.season_type, p.week, p.pid, d.team AS defteam, o.team AS offteam,
       p.trg AS gsis_id, s.player_display_name AS name,
       CASE w.position WHEN 'FB' THEN 'RB' ELSE w.position END AS position,
       p.loc, substr(p.loc, 2, 1) AS lane,            -- L / M / R
       substr(p.loc, 1, 1) AS depth_tier,             -- S short / D deep (FTN's own split)
       p.dot AS air_yards, p.comp AS complete, p.yds AS yards,
       CASE WHEN p.td = 1 AND p.td_type = 'REC' THEN 1 ELSE 0 END AS rec_td,
       r.route
FROM core_ftn_plays p
JOIN team_aliases d ON d.abbr = p."def" AND p.season BETWEEN d.season_from AND d.season_to
JOIN team_aliases o ON o.abbr = p."off" AND p.season BETWEEN o.season_from AND o.season_to
LEFT JOIN mart_player_week w ON w.season = p.season AND w.season_type = p.season_type
                            AND w.week = p.week AND w.gsis_id = p.trg
LEFT JOIN core_player_stats s ON s.season = p.season AND s.season_type = p.season_type
                             AND s.week = p.week AND s.player_id = p.trg
LEFT JOIN (SELECT pid, skp1 AS gsis_id, route1 AS route FROM core_ftn_participation WHERE route1 IS NOT NULL AND route1 != ''
           UNION ALL SELECT pid, skp2, route2 FROM core_ftn_participation WHERE route2 IS NOT NULL AND route2 != ''
           UNION ALL SELECT pid, skp3, route3 FROM core_ftn_participation WHERE route3 IS NOT NULL AND route3 != ''
           UNION ALL SELECT pid, skp4, route4 FROM core_ftn_participation WHERE route4 IS NOT NULL AND route4 != ''
           UNION ALL SELECT pid, skp5, route5 FROM core_ftn_participation WHERE route5 IS NOT NULL AND route5 != '') r
       ON r.pid = p.pid AND r.gsis_id = p.trg
WHERE p.type = 'PASS' AND p.season_type = 'REG' AND p.trg IS NOT NULL AND p.loc IS NOT NULL AND p.dot IS NOT NULL;

-- Dropbacks and EPA faced, per defense-week (nflverse pbp). Games = the weeks a defense appears here.
CREATE VIEW mart_def_dropback_week AS
SELECT season, season_type, week, defteam, COUNT(*) AS dropbacks, SUM(epa) AS epa
FROM core_pbp
WHERE qb_dropback = 1 AND season_type = 'REG' AND defteam IS NOT NULL AND epa IS NOT NULL
GROUP BY season, season_type, week, defteam;
