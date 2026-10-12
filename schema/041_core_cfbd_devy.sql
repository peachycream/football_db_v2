-- Phase 14: CFB / devy tracker (PHASE14_PROMPT.md). Owners: registry/sources.toml.
-- CFBD columns = CFBD wire names verbatim (probed live 2026-10-10: stats/player/season, player/usage, roster).
-- Season grain: one raw file per season (CFBD full-season, all divisions). The season is final once the NFL
-- season it overlaps has moved on (fdb/loaders/cfbd.py); until then the file is re-fetched every run.

-- stats/player/season is LONG: one row per (player, team, category, statType). Only the categories a devy
-- manager reads are stored (passing, rushing, receiving, defensive, interceptions); kicking/punting/returns are not.
CREATE TABLE core_cfbd_player_season (
  season INTEGER NOT NULL,
  playerId TEXT NOT NULL,
  player TEXT,
  position TEXT,
  team TEXT NOT NULL,
  conference TEXT,
  category TEXT NOT NULL,
  statType TEXT NOT NULL,
  stat REAL NOT NULL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  UNIQUE (season, playerId, team, category, statType)
);
CREATE INDEX ix_cfbd_ps_player ON core_cfbd_player_season (season, playerId);

-- player/usage: `usage` is a nested object; its keys become usage_<key> columns (the only rename: a flatten).
CREATE TABLE core_cfbd_player_usage (
  season INTEGER NOT NULL,
  id TEXT NOT NULL,
  name TEXT,
  position TEXT,
  team TEXT NOT NULL,
  conference TEXT,
  usage_overall REAL,
  usage_pass REAL,
  usage_rush REAL,
  usage_firstDown REAL,
  usage_secondDown REAL,
  usage_thirdDown REAL,
  usage_standardDowns REAL,
  usage_passingDowns REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  UNIQUE (season, id, team)
);

-- roster: height (inches), weight (lb), class `year` (1-4). NO birthdate in CFBD: age is never derived.
CREATE TABLE core_cfbd_roster (
  season INTEGER NOT NULL,
  id TEXT NOT NULL,
  firstName TEXT,
  lastName TEXT,
  team TEXT NOT NULL,
  weight INTEGER,
  height INTEGER,
  jersey INTEGER,
  year INTEGER,
  position TEXT,
  homeCity TEXT,
  homeState TEXT,
  homeCountry TEXT,
  homeLatitude REAL,
  homeLongitude REAL,
  homeCountyFIPS TEXT,
  recruitIds TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  UNIQUE (season, id, team)
);
CREATE INDEX ix_cfbd_roster_id ON core_cfbd_roster (season, id);

-- User-entered state (exported to app_state/app_devy_roster.csv before every rebuild): the devy roster as
-- Turon's screenshots show it. `source_text`/`position`/`school_text` are the cell as written; the CFBD id comes
-- from devy_identity (the approved review sheet), never from a name. `line` = the row within the franchise's
-- block, `devy_slot` = the "Devy N" column.
CREATE TABLE app_devy_roster (
  league_id TEXT NOT NULL,
  franchise_id TEXT NOT NULL,
  franchise_name TEXT,
  line INTEGER NOT NULL,
  devy_slot INTEGER NOT NULL,
  source_text TEXT NOT NULL,
  position TEXT NOT NULL,
  school_text TEXT NOT NULL,
  seen_on TEXT,
  PRIMARY KEY (league_id, franchise_id, line, devy_slot)
);

-- The approved mapping (config/devy_identity.csv, built from data/devy_review.csv): the as-written cell
-- (text, position, school) -> CFBD id, with Turon's reason. Owner: devy.identity (builder).
CREATE TABLE devy_identity (
  source_text TEXT NOT NULL,
  position TEXT NOT NULL,
  school_text TEXT NOT NULL,
  cfbd_id TEXT,
  reason TEXT,
  PRIMARY KEY (source_text, position, school_text)
);
