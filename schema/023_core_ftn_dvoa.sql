-- FTN Fantasy StatsHub team DVOA (owner per table: registry/sources.toml). Client: fdb/ftnfantasy.py.
-- Source columns keep the source's own names and case (rule 3). Framework columns: season, season_type, week.
-- One row per team that PLAYED that schedule week (a bye team has no row). Single-week values: the request
-- names one week, so games = 1. Seasons 2018+ (the site answers [] before); REG weeks only for now.

CREATE TABLE core_ftn_dvoa_team_week (
  season INTEGER NOT NULL,
  season_type TEXT NOT NULL CHECK (season_type = 'REG'),
  week INTEGER NOT NULL CHECK (week BETWEEN 1 AND 18),
  team TEXT NOT NULL,              -- FTN's spelling (ARZ, BLT, CLV, HST); team_aliases maps it
  id INTEGER,                      -- FTN's own team id (1-32)
  games INTEGER,
  wins INTEGER,
  losses INTEGER,
  ties INTEGER,
  offDvoa REAL,                    -- offense DVOA: higher is better
  defDvoa REAL,                    -- defense DVOA: LOWER is better (points allowed per play vs average)
  totalDvoa REAL,
  offVoaUnadj REAL,
  defVoaUnadj REAL,
  offenseBaseline REAL,
  defenseBaseline REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, season_type, week, team)
);

-- The one place the names change (rule 3), and the franchise is resolved through team_aliases.
-- DVOA is a published rate: read it per week, or weight it yourself; never average these blindly across games.
CREATE VIEW mart_team_dvoa_week AS
SELECT d.season, d.season_type, d.week, a.team,
       d.team AS source_team, d.games, d.wins, d.losses, d.ties,
       d.offDvoa AS off_dvoa, d.defDvoa AS def_dvoa, d.totalDvoa AS total_dvoa,
       d.offVoaUnadj AS off_voa_unadj, d.defVoaUnadj AS def_voa_unadj,
       d.offenseBaseline AS offense_baseline, d.defenseBaseline AS defense_baseline
FROM core_ftn_dvoa_team_week d
JOIN team_aliases a ON a.abbr = d.team AND d.season BETWEEN a.season_from AND a.season_to;
