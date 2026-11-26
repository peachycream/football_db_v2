-- Defender on each target (migration 059; 058 already applied and pushed, so this replaces the view).
-- FTN participation pairs each charted skill player (skpN) with the defender on him (defN, defN_pos); the pair for the
-- TARGETED player is carried here. Exact gsis ids throughout; the defender's name is the identity table's on that id.
-- It is FTN's charted assignment, not a coverage grade. 2026+ only: FTN's 2021-22 slots list one player twice on a few
-- plays (45 duplicate play/player pairs), and route labels do not exist before 2026 anyway.
DROP VIEW mart_def_target_play;

CREATE VIEW mart_def_target_play AS
SELECT p.season, p.season_type, p.week, p.pid, d.team AS defteam, o.team AS offteam,
       p.trg AS gsis_id, s.player_display_name AS name,
       CASE w.position WHEN 'FB' THEN 'RB' ELSE w.position END AS position,
       p.loc, substr(p.loc, 2, 1) AS lane,            -- L / M / R
       substr(p.loc, 1, 1) AS depth_tier,             -- S short / D deep (FTN's own split)
       p.dot AS air_yards, p.comp AS complete, p.yds AS yards,
       CASE WHEN p.td = 1 AND p.td_type = 'REC' THEN 1 ELSE 0 END AS rec_td,
       r.route, r.def_id AS defender_id, ds.display_name AS defender_name, r.def_pos AS defender_pos
FROM core_ftn_plays p
JOIN team_aliases d ON d.abbr = p."def" AND p.season BETWEEN d.season_from AND d.season_to
JOIN team_aliases o ON o.abbr = p."off" AND p.season BETWEEN o.season_from AND o.season_to
LEFT JOIN mart_player_week w ON w.season = p.season AND w.season_type = p.season_type
                            AND w.week = p.week AND w.gsis_id = p.trg
LEFT JOIN core_player_stats s ON s.season = p.season AND s.season_type = p.season_type
                             AND s.week = p.week AND s.player_id = p.trg
LEFT JOIN (SELECT pid, skp1 AS gsis_id, NULLIF(route1, '') AS route, def1 AS def_id, def1_pos AS def_pos FROM core_ftn_participation WHERE skp1 IS NOT NULL
           UNION ALL SELECT pid, skp2, NULLIF(route2, ''), def2, def2_pos FROM core_ftn_participation WHERE skp2 IS NOT NULL
           UNION ALL SELECT pid, skp3, NULLIF(route3, ''), def3, def3_pos FROM core_ftn_participation WHERE skp3 IS NOT NULL
           UNION ALL SELECT pid, skp4, NULLIF(route4, ''), def4, def4_pos FROM core_ftn_participation WHERE skp4 IS NOT NULL
           UNION ALL SELECT pid, skp5, NULLIF(route5, ''), def5, def5_pos FROM core_ftn_participation WHERE skp5 IS NOT NULL) r
       ON r.pid = p.pid AND r.gsis_id = p.trg
LEFT JOIN players ds ON ds.gsis_id = r.def_id
WHERE p.season >= 2026 AND p.type = 'PASS' AND p.season_type = 'REG' AND p.trg IS NOT NULL AND p.loc IS NOT NULL AND p.dot IS NOT NULL;
