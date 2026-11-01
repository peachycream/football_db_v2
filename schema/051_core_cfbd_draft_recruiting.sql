-- Phase 15e-3 (PHASE15E3_SPEC.md): CFBD draft picks (loader cfbd.draft_picks) and recruiting players (loader cfbd.recruiting_players).
-- Source field names verbatim; nested `hometownInfo` is stored as JSON text. `season` is the request's year (= `year`, checked).
-- The draft table joins core_nflverse_draft_picks on (season, overall) ONLY in builder idp_prospect.cfbd_bridge, never here.
CREATE TABLE core_cfbd_draft_picks (
  season INTEGER NOT NULL,
  collegeAthleteId INTEGER,
  nflAthleteId INTEGER,
  collegeId INTEGER,
  collegeTeam TEXT,
  collegeConference TEXT,
  nflTeamId INTEGER,
  nflTeam TEXT,
  year INTEGER NOT NULL,
  overall INTEGER NOT NULL,
  round INTEGER,
  pick INTEGER,
  name TEXT,
  position TEXT,
  height INTEGER,
  weight INTEGER,
  preDraftRanking INTEGER,
  preDraftPositionRanking INTEGER,
  preDraftGrade INTEGER,
  hometownInfo TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  UNIQUE (season, overall)
);

CREATE TABLE core_cfbd_recruiting_players (
  season INTEGER NOT NULL,
  id TEXT NOT NULL,
  athleteId TEXT,
  recruitType TEXT,
  year INTEGER NOT NULL,
  ranking INTEGER,
  name TEXT,
  school TEXT,
  committedTo TEXT,
  position TEXT,
  height REAL,
  weight INTEGER,
  stars INTEGER,
  rating REAL,
  city TEXT,
  stateProvince TEXT,
  country TEXT,
  hometownInfo TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  UNIQUE (season, id)
);
CREATE INDEX ix_cfbd_recruit_athlete ON core_cfbd_recruiting_players (athleteId);
