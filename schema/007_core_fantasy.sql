-- Fantasy platforms (REBUILD_DESIGN §4, Phase 3). One owner per table; see
-- registry/sources.toml. Source wire names are kept verbatim. Columns that are
-- NOT source fields are framework columns: season, season_type, league_id,
-- snapshot_at, and the few flattening names noted inline.
-- Leagues and seasons in scope come from config/my_franchises.toml.
--
-- MFL `$t` text nodes ({"$t": "*.75"}) are stored as their text: a cast, not a rename.
-- Nested source objects kept for later phases are stored as JSON text under their own name.

-- MFL TYPE=league (scalar settings). Subset: pool/roster/season settings; UI prefs dropped.
CREATE TABLE core_mfl_league (
  season                 INTEGER NOT NULL,
  league_id              TEXT NOT NULL,
  id                     TEXT NOT NULL,
  name                   TEXT,
  baseURL                TEXT,
  rostersPerPlayer       INTEGER,      -- owners a player may have per pool (55757 = 2)
  playerLimitUnit        TEXT,         -- the POOL: LEAGUE | CONFERENCE | DIVISION
  rosterSize             INTEGER,
  taxiSquad              INTEGER,
  injuredReserve         INTEGER,
  startWeek              INTEGER,
  endWeek                INTEGER,
  lastRegularSeasonWeek  INTEGER,
  keeperType             TEXT,
  h2h                    TEXT,
  precision              INTEGER,
  bestLineup             TEXT,
  usesSalaries           TEXT,
  usesContractYear       TEXT,
  loadRosters            TEXT,
  draft_kind             TEXT,
  draftPlayerPool        TEXT,
  currentWaiverType      TEXT,
  nflPoolType            TEXT,
  standingsSort          TEXT,
  partialLineupAllowed   TEXT,
  lockout                TEXT,
  starters               TEXT,         -- JSON: lineup requirements (Phase 6)
  rosterLimits           TEXT,         -- JSON, where the league has it
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id)
);

-- MFL TYPE=league -> franchises.franchise. Contact fields (email, phone, cell,
-- address...) are deliberately NOT stored; they stay in the local raw file only.
CREATE TABLE core_mfl_franchises (
  season               INTEGER NOT NULL,
  league_id            TEXT NOT NULL,
  id                   TEXT NOT NULL,
  name                 TEXT,
  abbrev               TEXT,
  division             TEXT,
  owner_name           TEXT,
  username             TEXT,
  icon                 TEXT,
  logo                 TEXT,
  waiverSortOrder      TEXT,
  bbidAvailableBalance TEXT,
  future_draft_picks   TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, id)
);

-- MFL TYPE=league -> divisions.division / conferences.conference.
CREATE TABLE core_mfl_divisions (
  season      INTEGER NOT NULL,
  league_id   TEXT NOT NULL,
  id          TEXT NOT NULL,
  name        TEXT,
  conference  TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, id)
);
CREATE TABLE core_mfl_conferences (
  season      INTEGER NOT NULL,
  league_id   TEXT NOT NULL,
  id          TEXT NOT NULL,
  name        TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, id)
);

-- MFL TYPE=rosters, one row per roster slot per SNAPSHOT. History is kept: one
-- snapshot per UTC day (raw retention 'daily'); mart_roster_ownership reads the latest.
-- franchise_id / week = the parent franchise element's `id` / `week` (flattening:
-- the player element has its own `id`).
CREATE TABLE core_mfl_rosters (
  season        INTEGER NOT NULL,
  league_id     TEXT NOT NULL,
  snapshot_at   TEXT NOT NULL,        -- raw fetch stamp (UTC), e.g. 20260927T013426173731Z
  franchise_id  TEXT NOT NULL,
  week          INTEGER,
  id            TEXT NOT NULL,        -- MFL player id
  status        TEXT NOT NULL,        -- ROSTER | TAXI_SQUAD | INJURED_RESERVE
  drafted       TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, snapshot_at, franchise_id, id)
);

-- MFL TYPE=rules, flattened: positionRules[].rule[] with the group's `positions` on
-- each rule. Stored verbatim; catch-all interpretation (v1 diag_proj_14) is a mart
-- concern (Phase 6). No sequence column: MFL returns the groups in a different ORDER
-- on every call (seen 2026-09-26), so position in the payload is not data. The rule
-- itself is the key (unique in all 6 leagues); an exact duplicate fails the load.
CREATE TABLE core_mfl_rules (
  season     INTEGER NOT NULL,
  league_id  TEXT NOT NULL,
  positions  TEXT NOT NULL,           -- e.g. 'QB|RB|WR|TE|DT|DE|LB|CB|S'
  event      TEXT NOT NULL,
  "range"    TEXT NOT NULL,
  points     TEXT NOT NULL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, positions, event, "range", points)
);

-- MFL TYPE=playerScores&W=<week>: MFL's REPORTED points (IDP calibration truth).
-- Week-complete gate applies; raw is final only 7 days after the week (stat corrections).
CREATE TABLE core_mfl_player_scores (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  id           TEXT NOT NULL,
  score        REAL,
  isAvailable  INTEGER,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, id)
);

-- MFL TYPE=players&DETAILS=1, league-scoped (devy leagues carry college players).
CREATE TABLE core_mfl_players (
  season            INTEGER NOT NULL,
  league_id         TEXT NOT NULL,
  id                TEXT NOT NULL,
  name              TEXT,              -- 'Last, First' as MFL writes it
  position          TEXT,
  team              TEXT,
  status            TEXT,
  birthdate         TEXT,              -- epoch seconds, verbatim
  draft_year        TEXT,
  draft_round       TEXT,
  draft_pick        TEXT,
  draft_team        TEXT,
  college           TEXT,
  height            TEXT,
  weight            TEXT,
  jersey            TEXT,
  espn_id           TEXT,
  cbs_id            TEXT,
  stats_id          TEXT,
  stats_global_id   TEXT,
  rotowire_id       TEXT,
  rotoworld_id      TEXT,
  sportsdata_id     TEXT,
  nfl_id            TEXT,
  fleaflicker_id    TEXT,
  twitter_username  TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, id)
);

-- Sleeper /league/<id>. Chat/last-message fields dropped. settings, scoring_settings,
-- roster_positions, metadata kept as JSON text (Sleeper scoring is deferred, §10.3).
CREATE TABLE core_sleeper_league (
  season              INTEGER NOT NULL,
  league_id           TEXT NOT NULL,
  name                TEXT,
  season_type         TEXT,
  status              TEXT,
  sport               TEXT,
  total_rosters       INTEGER,
  previous_league_id  TEXT,
  draft_id            TEXT,
  avatar              TEXT,
  settings            TEXT,
  scoring_settings    TEXT,
  roster_positions    TEXT,
  metadata            TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id)
);

-- Sleeper /league/<id>/users.
CREATE TABLE core_sleeper_users (
  season        INTEGER NOT NULL,
  league_id     TEXT NOT NULL,
  user_id       TEXT NOT NULL,
  display_name  TEXT,
  is_owner      INTEGER,
  is_bot        INTEGER,
  avatar        TEXT,
  metadata      TEXT,                  -- JSON; team_name lives here
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, user_id)
);

-- Sleeper /league/<id>/rosters, one row per element of a roster's `players` list,
-- per SNAPSHOT (daily retention, like MFL). in_starters / in_taxi / in_reserve say
-- whether that id is also in the roster's `starters` / `taxi` / `reserve` list
-- (framework flags; the lists are always subsets of `players`, verified live).
CREATE TABLE core_sleeper_rosters (
  season       INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  snapshot_at  TEXT NOT NULL,
  roster_id    INTEGER NOT NULL,
  owner_id     TEXT,
  co_owners    TEXT,                   -- JSON
  player_id    TEXT NOT NULL,
  in_starters  INTEGER NOT NULL,
  in_taxi      INTEGER NOT NULL,
  in_reserve   INTEGER NOT NULL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, snapshot_at, roster_id, player_id)
);

-- Sleeper /players/nfl (~15 MB, current state). Identity source for sleeper ids
-- (fdb/identity.py): gsis_id is source-native but name-checked, like DynastyProcess.
CREATE TABLE core_sleeper_players (
  player_id             TEXT PRIMARY KEY,
  first_name            TEXT,
  last_name             TEXT,
  full_name             TEXT,
  position              TEXT,
  fantasy_positions     TEXT,          -- JSON
  team                  TEXT,
  team_abbr             TEXT,
  status                TEXT,
  active                INTEGER,
  sport                 TEXT,
  years_exp             INTEGER,
  birth_date            TEXT,
  age                   REAL,
  height                TEXT,
  weight                TEXT,
  college               TEXT,
  number                TEXT,
  depth_chart_position  TEXT,
  depth_chart_order     TEXT,
  injury_status         TEXT,
  gsis_id               TEXT,          -- verbatim; some carry stray whitespace
  espn_id               TEXT,
  yahoo_id              TEXT,
  sportradar_id         TEXT,
  rotowire_id           TEXT,
  rotoworld_id          TEXT,
  fantasy_data_id       TEXT,
  stats_id              TEXT,
  swish_id              TEXT,
  search_full_name      TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id)
);

CREATE INDEX ix_core_mfl_rosters_id ON core_mfl_rosters(id);
CREATE INDEX ix_core_sleeper_rosters_pid ON core_sleeper_rosters(player_id);
