-- Phase 11: MFL liveScoring (TYPE=liveScoring&W=<week in progress>): each franchise's score SO FAR and each starter's live score,
-- one snapshot per fetch like core_mfl_projected_scores. It is a current-state feed that stops being true the moment the games
-- end (the final numbers are core_mfl_weekly_results), so only the week IN PROGRESS (first kickoff passed, not complete) is
-- fetched and no snapshot is ever final. Probed live 2026-10-08 (30590 wk5, before kickoff): score '0.00', playersYetToPlay '28',
-- gameSecondsRemaining '100800' (= 28 starters x 3600), each player gameSecondsRemaining '3600'.
-- A franchise plays two games a week with one lineup, so the franchise rows repeat per game (id, opponent_id) and the player rows
-- are per franchise.
CREATE TABLE core_mfl_live_scores (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  snapshot_at  TEXT NOT NULL,        -- raw fetch stamp (UTC)
  id           TEXT NOT NULL,        -- the franchise
  opponent_id  TEXT NOT NULL,        -- '' = no opponent
  isHome       INTEGER,
  score        REAL NOT NULL,        -- points so far
  gameSecondsRemaining INTEGER,
  playersYetToPlay INTEGER,
  playersCurrentlyPlaying INTEGER,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, snapshot_at, id, opponent_id)
);

CREATE TABLE core_mfl_live_players (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  snapshot_at  TEXT NOT NULL,
  franchise_id TEXT NOT NULL,
  id           TEXT NOT NULL,        -- MFL player id
  status       TEXT,                 -- starter | nonstarter
  score        REAL,                 -- points so far
  gameSecondsRemaining INTEGER,
  updatedStats TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, snapshot_at, franchise_id, id)
);
