-- Identity layer (REBUILD_DESIGN §3). Built by fdb/identity.py from the core
-- identity sources + identity_overrides.csv; fully rebuilt every run, never hand-edited.
-- Owner: identity.build.

-- One row per human, keyed on gsis_id. Values come from nflverse players.csv;
-- a gsis_id that is on a weekly roster but not yet in players.csv (new signings)
-- is added from its latest roster row (players_source = 'rosters_weekly').
CREATE TABLE players (
  gsis_id            TEXT PRIMARY KEY,
  display_name       TEXT NOT NULL,
  first_name         TEXT,
  last_name          TEXT,
  birth_date         TEXT,
  position           TEXT,
  position_group     TEXT,
  height             INTEGER,
  weight             INTEGER,
  college            TEXT,
  rookie_season      INTEGER,
  last_season        INTEGER,
  latest_team        TEXT,
  draft_year         INTEGER,
  draft_round        INTEGER,
  draft_pick_overall INTEGER,           -- nflverse draft_pick IS the overall pick; one definition
  players_source     TEXT NOT NULL CHECK (players_source IN ('nflverse_players', 'rosters_weekly'))
);

-- Every other id -> gsis_id. (source, source_id) is the key: one source id names one human.
CREATE TABLE player_ids (
  source     TEXT NOT NULL,      -- pff, pfr, espn, otc, nfl, esb, smart, sleeper, mfl, sportradar, yahoo, rotowire, fantasy_data
  source_id  TEXT NOT NULL,
  gsis_id    TEXT NOT NULL REFERENCES players(gsis_id),
  method     TEXT NOT NULL CHECK (method IN ('source_native', 'id_map', 'jersey_bridge', 'manual')),
  evidence   TEXT NOT NULL,
  PRIMARY KEY (source, source_id)
);
CREATE INDEX ix_player_ids_gsis ON player_ids(gsis_id, source);

-- Claims that were refused. Reported, never guessed; fix with identity_overrides.csv.
CREATE TABLE identity_quarantine (
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  claimed_gsis  TEXT,
  claimed_name  TEXT,
  evidence      TEXT NOT NULL,
  reason        TEXT NOT NULL
);
CREATE INDEX ix_identity_quarantine ON identity_quarantine(source, source_id);
