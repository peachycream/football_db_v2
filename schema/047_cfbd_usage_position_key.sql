-- Phase 15b: CFBD lists a player under two positions on one team (QB and WR, RB and WR) with a separate usage row for each
-- (35 keys in 2021, 78 in 2024). Phase 14's key (season, id, team) could not hold both. The key now includes position.
-- Rebuilt by copy, not RENAME: SQLite's RENAME checks every view, and the mart views that read this table's mart are not
-- all recreated here.
CREATE TEMP TABLE _usage_keep AS SELECT * FROM core_cfbd_player_usage;
DROP TABLE core_cfbd_player_usage;
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
  UNIQUE (season, id, team, position)
);
INSERT INTO core_cfbd_player_usage SELECT season, id, name, position, team, conference, usage_overall, usage_pass, usage_rush,
  usage_firstDown, usage_secondDown, usage_thirdDown, usage_standardDowns, usage_passingDowns, load_id FROM _usage_keep;
DROP TABLE _usage_keep;
