-- Phase 11: MFL weeklyResults (TYPE=weeklyResults&W=<week>), reported results of fantasy games.
-- Leagues and seasons in scope come from config/my_franchises.toml (history_seasons for matchup history).
--
-- Found by the live probe (2026-10-03, league 30590): a franchise can play MORE THAN ONE game in a week
-- (30590: two, 32 matchups / 64 slots for 32 franchises), with the SAME score in each. So:
--   * core_mfl_weekly_results is one row per franchise PER GAME: (id, opponent_id). Count games from here;
--     count a week's points ONCE per franchise (never SUM(score) over this table).
--   * the lineup (identical in both games) lives once per franchise-week in core_mfl_lineups.
-- An unplayed week has no score and `result` = 'T' for everyone; only completed weeks are ever loaded.
-- Source names are kept verbatim; `opponent_id` and `franchise_id` are framework columns (the other
-- franchise of the matchup element / the franchise element a player sits under).

CREATE TABLE core_mfl_weekly_results (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  id           TEXT NOT NULL,        -- the franchise
  opponent_id  TEXT NOT NULL,        -- '' = no opponent in the matchup element (a bye)
  isHome       INTEGER,
  score        REAL,
  adj_score    REAL,                 -- commissioner adjustment already INCLUDED in score (2021 wk1: -1000 on two franchises)
  result       TEXT,                 -- W | L | T as MFL reports; checked against the scores on load
  opt_pts      REAL,                 -- points of the best possible lineup
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, id, opponent_id)
);
CREATE INDEX ix_mfl_wr_franchise ON core_mfl_weekly_results (league_id, id, season, week);

-- Player rows of weeklyResults franchise.player[]: who started, who did not, and the player's score.
CREATE TABLE core_mfl_lineups (
  season       INTEGER NOT NULL,
  season_type  TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  week         INTEGER NOT NULL,
  league_id    TEXT NOT NULL,
  franchise_id TEXT NOT NULL,
  id           TEXT NOT NULL,        -- the MFL player id (league-scoped for 0800-0999 devy ids)
  status       TEXT,                 -- starter | nonstarter
  shouldStart  INTEGER,
  score        REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, league_id, week, franchise_id, id)
);
