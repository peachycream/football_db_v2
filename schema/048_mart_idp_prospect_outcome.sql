-- Phase 15c (IDP prospect model): NFL outcomes of drafted defenders, years 1-3. Builder `idp_prospect.outcomes`
-- (fdb/idp_prospect.py). Keyed on gsis_id from core_nflverse_draft_picks (exact id, never a name).
-- SUMS ONLY: points per game and snaps per game are computed at read time. `points` is the catch-all league's
-- scoring of the season's COUNTS, summed (fdb/scoring.py rules of league 30590, the 2026 rule set applied to every season).
--
-- One row per drafted defender per NFL season in years 1-3 (year_index 1 = the draft season) that has been played.
-- A year with no defensive snap in any regular-season week is a row with games = 0, not a missing row.
-- years_observed: how many of the player's years 1-3 are closed seasons (a 2025 draftee has 1, a 2024 draftee 2);
-- it is repeated on every row so a reader can apply the right-censoring rule without a join.
CREATE TABLE mart_idp_prospect_outcome (
  gsis_id        TEXT    NOT NULL,
  pff_id         TEXT,                  -- players.pff_id, for joining college rows
  draft_season   INTEGER NOT NULL,
  draft_overall  INTEGER,
  year_index     INTEGER NOT NULL CHECK (year_index BETWEEN 1 AND 3),
  nfl_season     INTEGER NOT NULL,
  years_observed INTEGER NOT NULL,
  position_group TEXT,                  -- DT / DE / LB / CB / S: PFF's position that season (most snaps); NULL if no snaps
  games          INTEGER NOT NULL,      -- regular-season weeks with a defensive snap
  snaps          INTEGER NOT NULL,      -- defensive snaps
  points         REAL    NOT NULL,      -- catch-all points, summed over the season's weeks
  finish         INTEGER,               -- rank by points among that group's players that season (1 = best); NULL if no snaps
  group_players  INTEGER,               -- players in that group-season (the denominator of finish)
  top12          INTEGER NOT NULL,      -- finish <= 12
  top24          INTEGER NOT NULL,      -- finish <= 24
  PRIMARY KEY (gsis_id, year_index)
);
CREATE INDEX ix_mart_idp_prospect_outcome_draft ON mart_idp_prospect_outcome(draft_season, position_group);
