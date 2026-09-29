-- Expected tackles and sacks, v2's own model (REBUILD_DESIGN §6.1, Phase 7b): builder `idp_model.build`
-- (fdb/idp_model.py). Keyed on gsis_id from the start; never the name-matched vendor CSV.
-- SUMS ONLY: tackles vs expected, per-game rates and percentiles are computed at read time.

-- Per defender-week. expected = sum over the scrimmage plays the player was ON THE FIELD for of
-- P(tackle credit | his position group, play kind, ball-carrier gap, ball-carrier depth), with
-- the probabilities fitted on 2016-2024 (see mart_idp_tackle_rates). actual = every pbp tackle
-- credit slot (solo / with-assist / assist) on those plays, the convention v1 settled.
CREATE TABLE mart_idp_expected_tackles_week (
  season                INTEGER NOT NULL,
  season_type           TEXT    NOT NULL,
  week                  INTEGER NOT NULL,
  gsis_id               TEXT    NOT NULL,
  position_group        TEXT    NOT NULL,   -- DT / DE / LB / CB / S (PFF's position that season)
  run_plays             INTEGER NOT NULL,   -- on-field scrimmage plays that were runs (incl. scrambles)
  pass_plays            INTEGER NOT NULL,   -- dropbacks: completions, incompletions, sacks
  actual_tackles_run    INTEGER NOT NULL,
  actual_tackles_pass   INTEGER NOT NULL,
  expected_tackles_run  REAL    NOT NULL,
  expected_tackles_pass REAL    NOT NULL,
  on_field_source       TEXT    NOT NULL,   -- 'nflverse' (participation) / 'ftn' (all-22)
  PRIMARY KEY (season, season_type, week, gsis_id)
);
CREATE INDEX ix_mart_idp_xt_player ON mart_idp_expected_tackles_week(gsis_id, season);

-- The fitted tackle-probability table: one row per cell, with the counts it came from.
CREATE TABLE mart_idp_tackle_rates (
  position_group TEXT    NOT NULL,
  kind           TEXT    NOT NULL,   -- run / complete / incomplete / sack
  gap            TEXT    NOT NULL,   -- run: end/tackle/guard/middle/none; pass: outside/middle/none
  depth          TEXT    NOT NULL,   -- ball-carrier yards gained bucket
  player_plays   INTEGER NOT NULL,   -- on-field player-plays in the cell (fit seasons)
  credits        INTEGER NOT NULL,
  rate           REAL    NOT NULL,   -- shrunk toward the (group, kind, depth) then (group, kind) rate
  PRIMARY KEY (position_group, kind, gap, depth)
);

-- Per rusher-week: expected sacks = pass-rush wins x the position group's sacks-per-win,
-- fitted 2016-2024 (mart_idp_sack_rates). Counts from PFF defense/pass_rush.
CREATE TABLE mart_idp_expected_sacks_week (
  season            INTEGER NOT NULL,
  season_type       TEXT    NOT NULL,
  week              INTEGER NOT NULL,
  gsis_id           TEXT    NOT NULL,
  position_group    TEXT    NOT NULL,   -- ED -> DE, DI -> DT, else PFF's position
  pass_rush_snaps   INTEGER NOT NULL,
  pass_rush_opp     INTEGER NOT NULL,
  pass_rush_wins    INTEGER NOT NULL,
  sacks             INTEGER NOT NULL,
  expected_sacks    REAL    NOT NULL,
  PRIMARY KEY (season, season_type, week, gsis_id)
);

CREATE TABLE mart_idp_sack_rates (
  position_group TEXT    NOT NULL PRIMARY KEY,
  wins           INTEGER NOT NULL,
  sacks          INTEGER NOT NULL,
  rate           REAL    NOT NULL
);
