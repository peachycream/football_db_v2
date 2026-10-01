-- Player Dashboard Trinity panel. Numbered 024 on purpose: 023 is reserved for a migration on another in-flight
-- branch, so the two never write the same migration name.
--
-- DD's stored season score, one row per human. core_trinity_scores holds DD's rows verbatim, and DD builds
-- them by NAME, so the same Sleeper id can sit on two rows ("Tank Dell" / "Nathaniel Dell"). The apps read
-- marts only, and a number attached to the wrong or an ambiguous id would be a name guess in disguise, so
-- this view keeps only ids DD stored ONCE in a season and joins gsis through player_ids (exact key).
CREATE VIEW mart_trinity_season_stored AS
SELECT c.season, p.gsis_id, c.sleeper_id, c.player_name, c.position, c.team,
       c.trinity_score, c.ppg, c.games, c.tier, c.rank
FROM core_trinity_scores c
JOIN player_ids p ON p.source = 'sleeper' AND p.source_id = c.sleeper_id
WHERE (c.season, c.sleeper_id) IN (SELECT season, sleeper_id FROM core_trinity_scores
                                   WHERE sleeper_id IS NOT NULL GROUP BY season, sleeper_id HAVING COUNT(*) = 1);
