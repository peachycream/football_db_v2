-- Phase 11: the NEXT UNPLAYED week's pairings and lineups (MFL weeklyResults before the games), kept as a
-- snapshot per fetch like core_mfl_projected_scores. core_mfl_weekly_results only holds completed weeks, so the
-- card's PREVIEW reads these. Probed live 2026-10-03 (30590 wk4): an unplayed week answers `id`, `isHome`,
-- `starters`, `nonstarters`, `player[{id,status}]` and result = 'T' / no score for everyone (not stored).
-- A franchise can play several games a week (30590: two), so a game is (id, opponent_id) as in weekly_results.
CREATE TABLE core_mfl_upcoming_games (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  snapshot_at  TEXT NOT NULL,        -- raw fetch stamp (UTC)
  id           TEXT NOT NULL,        -- the franchise
  opponent_id  TEXT NOT NULL,        -- '' = no opponent (a bye)
  isHome       INTEGER,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, snapshot_at, id, opponent_id)
);

CREATE TABLE core_mfl_upcoming_lineups (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  snapshot_at  TEXT NOT NULL,
  franchise_id TEXT NOT NULL,
  id           TEXT NOT NULL,        -- MFL player id
  status       TEXT,                 -- starter | nonstarter
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, snapshot_at, franchise_id, id)
);
