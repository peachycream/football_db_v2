-- Phase 11: the Matchup of the Week card's data (builder `matchup.build`, fdb/matchup.py). The card, the Discord job
-- and any page read ONLY these three tables.
--
-- One row per GAME (an unordered pair of franchises in a week). A franchise can play several games a week (30590:
-- two) with one lineup and one score, so lineups live per FRANCHISE-WEEK in the two child tables, not per game.
-- home = the franchise MFL flags isHome; away = the other.
--
-- state  FINAL    results are LOADED (core_mfl_weekly_results has the week); actuals come from there and core_mfl_lineups
--        LIVE     the NFL week has kicked off and the results are not loaded: in progress, or complete per the schedule and
--                 waiting for the weekly job (a FINAL row without scores would be false). Pairings/lineups: the latest
--                 upcoming snapshot
--        PREVIEW  the week has not kicked off: the same
--   It is derived from the SCHEDULE and from which results exist, never from a score or from MFL's `result` (an unplayed
--   week reads 'T', no score).
-- Records and points-for are through the weeks BEFORE this one, regular season only (week <= lastRegularSeasonWeek),
--   a week's points counted once per franchise. A franchise's record counts every game (30590: two a week).
-- proj_*  from the LAST projection snapshot taken before the week's first kickoff (proj_snapshot_at); NULL, never
--   guessed, when there is none (a list fetched after the games is partial; see core_mfl_projected_scores).
-- Rates are not stored: win probability is computed by the reader from the stored point totals.
-- series_*  regular-season meetings of the same two franchise ids in all loaded seasons, strictly before this game.
--   It assumes an MFL franchise id is the same owner across seasons (not audited for all 32; REBUILD_LOG open item).
CREATE TABLE mart_matchup_card (
  season        INTEGER NOT NULL,
  league_id     TEXT NOT NULL,
  week          INTEGER NOT NULL,
  season_type   TEXT NOT NULL,
  state         TEXT NOT NULL CHECK (state IN ('PREVIEW', 'LIVE', 'FINAL')),
  first_kickoff_utc TEXT,
  is_division_rivalry INTEGER NOT NULL,
  lineup_source TEXT NOT NULL,       -- 'weekly_results' | 'upcoming_snapshot'
  upcoming_snapshot_at TEXT,         -- the core_mfl_upcoming_* snapshot used (NULL for FINAL)
  proj_snapshot_at TEXT,             -- the projection snapshot used (NULL when none before kickoff)
  home_id TEXT NOT NULL, home_name TEXT, home_abbrev TEXT, home_division TEXT, home_logo TEXT, home_icon TEXT,
  home_color TEXT, home_color_alt TEXT,
  away_id TEXT NOT NULL, away_name TEXT, away_abbrev TEXT, away_division TEXT, away_logo TEXT, away_icon TEXT,
  away_color TEXT, away_color_alt TEXT,
  home_w INTEGER NOT NULL, home_l INTEGER NOT NULL, home_t INTEGER NOT NULL, home_pf REAL NOT NULL,
  away_w INTEGER NOT NULL, away_l INTEGER NOT NULL, away_t INTEGER NOT NULL, away_pf REAL NOT NULL,
  home_score REAL, away_score REAL,          -- FINAL only
  home_opt_pts REAL, away_opt_pts REAL,      -- FINAL only: best possible lineup
  home_proj REAL, away_proj REAL,            -- sum of the starters' projections; NULL without a pre-kickoff snapshot
  home_proj_missing INTEGER, away_proj_missing INTEGER,   -- starters the snapshot had no projection for
  series_meetings INTEGER NOT NULL, series_home_wins INTEGER NOT NULL, series_away_wins INTEGER NOT NULL,
  series_ties INTEGER NOT NULL,
  last_meeting_season INTEGER, last_meeting_week INTEGER, last_meeting_home_score REAL, last_meeting_away_score REAL,
  PRIMARY KEY (season, league_id, week, home_id, away_id)
);

-- One row per franchise-week-position group over the STARTERS. proj/actual are NULL when unknown.
CREATE TABLE mart_matchup_card_groups (
  season INTEGER NOT NULL, league_id TEXT NOT NULL, week INTEGER NOT NULL, franchise_id TEXT NOT NULL,
  grp TEXT NOT NULL,                 -- QB RB WR TE PK DL LB DB, or OTHER (a position the mapping does not know)
  n_starters INTEGER NOT NULL,
  proj REAL, actual REAL,
  PRIMARY KEY (season, league_id, week, franchise_id, grp)
);

-- The starters, joined to players through player_ids(mfl) only; an unresolved id keeps its MFL id and no name.
CREATE TABLE mart_matchup_card_players (
  season INTEGER NOT NULL, league_id TEXT NOT NULL, week INTEGER NOT NULL, franchise_id TEXT NOT NULL,
  source_player_id TEXT NOT NULL,
  gsis_id TEXT, display_name TEXT, position TEXT,
  grp TEXT NOT NULL,
  proj REAL, actual REAL,
  PRIMARY KEY (season, league_id, week, franchise_id, source_player_id)
);
