-- Phase 16b Stage 1 (PHASE16B_SPEC.md): the next-season outlook of NFL defenders. Builder `idp_outlook.build` (fdb/idp_outlook.py).
--
-- One row per candidate player-season (>= 300 snaps in season N, N from 2021, only closed seasons). `model` is 'ridge16a' for DT, S
-- and CB (the 16a PRIMARY model, trained only on candidates of seasons before N whose next season is closed by the end of N) and NULL
-- for DE and LB (the gate failed there: last year's points stay the baseline). Counts are stored; per-game rates are read-time.
-- `points_next_actual` is NULL exactly when season N+1 is not closed; a player with no row in a closed N+1 has 0.
CREATE TABLE mart_idp_outlook (
  gsis_id TEXT NOT NULL,
  season_n INTEGER NOT NULL,
  season_next INTEGER NOT NULL,
  position_group TEXT NOT NULL,       -- DE | DT | LB | S | CB (DE is the EDGE group)
  points_n REAL NOT NULL,
  games_n INTEGER NOT NULL,
  snaps_n INTEGER NOT NULL,
  points_prev REAL,                   -- season N-1, NULL when the player has no row there
  games_prev INTEGER,
  et_gap REAL,                        -- actual minus expected tackles in N (count), NULL when the expected-tackle mart has no row
  es_gap REAL,                        -- sacks minus expected sacks in N (count), NULL when the expected-sack mart has no row
  age_next REAL,                      -- years from birth date to 1 September of N+1, NULL without a birth date
  draft_year INTEGER,
  model TEXT,
  pred_points_next REAL,
  rank_pred INTEGER,                  -- within (season_n, group) among rows with a model; ties share the best rank
  rank_last INTEGER NOT NULL,         -- by points_n within (season_n, group); ties share the best rank
  points_next_actual REAL,
  PRIMARY KEY (gsis_id, season_n)
);
CREATE INDEX ix_mart_idp_outlook_season ON mart_idp_outlook(season_n, position_group);

CREATE TABLE mart_idp_outlook_model (
  season_n INTEGER NOT NULL,
  position_group TEXT NOT NULL,
  model TEXT NOT NULL,
  n_train INTEGER NOT NULL,
  first_train_n INTEGER NOT NULL,
  last_train_n INTEGER NOT NULL,
  alpha REAL NOT NULL,
  intercept REAL NOT NULL,
  features TEXT NOT NULL,             -- JSON list, the order of the four arrays below
  coef TEXT NOT NULL,                 -- JSON, on standardised features
  median TEXT NOT NULL,               -- training medians used to fill missing values
  mean TEXT NOT NULL,                 -- training mean after the fill
  scale TEXT NOT NULL,                -- training standard deviation after the fill (1 when constant)
  PRIMARY KEY (season_n, position_group)
);

-- Empirical zero-points-next-season counts over the training candidates, by age band. The rate is n_zero / n at read time; a cell with n < 25 is not shown.
CREATE TABLE mart_idp_outlook_exit (
  season_n INTEGER NOT NULL,
  position_group TEXT NOT NULL,
  age_band TEXT NOT NULL,             -- <25 | 25-27 | 28-30 | 31+
  n INTEGER NOT NULL,
  n_zero INTEGER NOT NULL,
  PRIMARY KEY (season_n, position_group, age_band)
);
