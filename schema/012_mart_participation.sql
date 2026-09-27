-- Participation seam (Phase 5). Built by fdb/participation.py (builder participation.seam):
-- one row per offensive scrimmage play; nflverse through 2025, FTN from 2026, the
-- source named on every row. Personnel is parsed from each source's own vocabulary.
CREATE TABLE mart_participation_personnel (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL,
  week         INTEGER NOT NULL,
  team         TEXT NOT NULL,        -- canonical (team_aliases.team), the offense
  source       TEXT NOT NULL CHECK (source IN ('nflverse', 'ftn')),
  game_key     TEXT NOT NULL,        -- nflverse game_id | FTN gid
  play_key     TEXT NOT NULL,        -- nflverse play_id | FTN pid
  play_type    TEXT NOT NULL CHECK (play_type IN ('pass', 'run')),
  n_rb         INTEGER NOT NULL,     -- backs incl. FB
  n_te         INTEGER NOT NULL,
  n_wr         INTEGER NOT NULL,
  personnel    TEXT NOT NULL,        -- '11' = 1 back, 1 TE
  PRIMARY KEY (source, game_key, play_key)
);
CREATE INDEX ix_mart_participation_personnel ON mart_participation_personnel(season, team);
