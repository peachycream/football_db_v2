-- Phase 11: MFL projectedScores (TYPE=projectedScores&W=<week>): per-PLAYER, per-WEEK projected fantasy
-- points under the LEAGUE'S scoring, one row per player per fetch.
--
-- Probed live 2026-10-03 (30590): leagues with different scoring answer differently (Gibbs wk4: 142.25 in
-- 30590/60398, 27.49 in 46276), leagues sharing rules answer identically, so the table is per league.
-- An UNPLAYED week's projections move (20 of 1,006 players changed within hours), so every fetch is kept as
-- a snapshot (`snapshot_at` = the raw fetch stamp), like core_mfl_rosters. Only the next unplayed week is
-- fetched. A list fetched AFTER the games is partial (30590 wk3: 895 players vs 1,007 unplayed; 166 of 896
-- starters had no projection), so it is NOT the pre-game projection: a reader takes, per week, the last
-- snapshot BEFORE the week's first kickoff. 2026 weeks 1-3 have none (the loader started on 2026-10-03; the
-- six wk3 snapshots in the table are post-game and partial).
-- The score is a single week's projection for ONE player; a franchise that plays several games in a week
-- uses the same lineup in each, so nothing here is per game.
CREATE TABLE core_mfl_projected_scores (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  snapshot_at  TEXT NOT NULL,        -- raw fetch stamp (UTC), e.g. 20261003T165915742987Z
  id           TEXT NOT NULL,        -- MFL player id (league-scoped for 0800-0999 devy ids)
  score        REAL,                 -- NULL where MFL sends a blank score
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, snapshot_at, id)
);
