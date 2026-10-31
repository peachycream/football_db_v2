-- Phase 15d (IDP prospect model): pre-draft features of drafted defenders. Builder `idp_prospect.features`
-- (fdb/idp_prospect.py). One row per drafted defender (core_nflverse_draft_picks side D, exact gsis_id), draft classes 2017+
-- (2016's feature season, 2015, is not loaded). College rows join by exact id: PFF NCAA player_id = players.pff_id (15a bridge).
-- COUNTS and measurements only: per-game and per-snap rates, speed score and snap-weighted pooling are read-time. Missing
-- combine data stays NULL with has_* indicators; nothing is imputed. NO leakage: every college season is <= draft_season - 1,
-- the combine and the draft slot precede the draft; nothing here reads an NFL outcome (the draft table's career columns,
-- players.rookie_season / last_season and the NFL-listed weight are never used).
CREATE TABLE mart_idp_prospect_features (
  gsis_id        TEXT    NOT NULL PRIMARY KEY,
  pff_id         TEXT,
  draft_season   INTEGER NOT NULL,
  draft_round    INTEGER,
  draft_pick     INTEGER,               -- overall pick
  draft_position TEXT,                  -- the draft table's own position field (DE, DT, DL, NT, OLB, ILB, LB, CB, S, SAF, DB)
  nfl_pff_position TEXT,                -- players.pff_position (DI, ED, LB, CB, S): the model's grouping field, NULL if never charted
  age_at_draft   REAL,                  -- years on April 25 of the draft year, from players.birth_date
  height_in      INTEGER,               -- combine height, else players.height (height_source says which)
  height_source  TEXT,
  weight_lb      INTEGER,               -- combine weight only (the NFL-listed weight is a later, in-career number)
  forty          REAL,
  bench          INTEGER,
  vertical       REAL,
  broad_jump     INTEGER,
  cone           REAL,
  shuttle        REAL,
  has_combine    INTEGER NOT NULL,
  has_forty      INTEGER NOT NULL,
  college_name   TEXT,
  college_conference TEXT,
  conference_tier TEXT,                 -- P5 / G5 / OTHER by the conference name; NULL when the conference is unknown
  has_college    INTEGER NOT NULL,      -- a PFF NCAA defense row exists for the player in some season <= draft_season - 1
  college_season INTEGER,               -- the player's latest such season
  college_season_gap INTEGER,           -- draft_season - 1 - college_season (0 = played the season before the draft)
  college_seasons INTEGER,              -- PFF NCAA seasons observed up to college_season
  first_college_season INTEGER,
  left_censored  INTEGER,               -- first_college_season is the first season loaded (2016): earlier seasons are unobserved
  age_at_college_season REAL,           -- years on September 1 of college_season
  college_position TEXT,
  -- final college season, counts
  c_games INTEGER, c_snaps_defense INTEGER, c_snaps_run_defense INTEGER, c_snaps_coverage INTEGER, c_snaps_pass_rush INTEGER,
  c_snaps_box INTEGER, c_snaps_slot INTEGER, c_snaps_dl INTEGER, c_snaps_offball INTEGER, c_snaps_corner INTEGER, c_snaps_fs INTEGER,
  c_tackles INTEGER, c_assists INTEGER, c_missed_tackles INTEGER, c_tfl INTEGER, c_stops INTEGER, c_sacks REAL, c_hits INTEGER,
  c_hurries INTEGER, c_pressures INTEGER, c_pass_break_ups INTEGER, c_interceptions INTEGER, c_forced_fumbles INTEGER,
  c_targets INTEGER, c_receptions INTEGER, c_cov_yards INTEGER,
  -- PFF grades are ratings, not counts: stored as given, pooled with the snap count that matches them at read time
  c_grade_defense REAL, c_grade_run_defense REAL, c_grade_coverage REAL, c_grade_pass_rush REAL, c_grade_tackle REAL,
  has_pass_rush  INTEGER NOT NULL,      -- a PFF NCAA pass-rush row exists for college_season
  pr_opp INTEGER, pr_wins INTEGER, pr_snaps INTEGER, pr_pressures INTEGER,
  pr_true_opp INTEGER, pr_true_wins INTEGER, pr_true_snaps INTEGER, pr_grade REAL,
  -- every PFF NCAA season up to college_season, summed (counts only)
  k_games INTEGER, k_snaps_defense INTEGER, k_tackles INTEGER, k_tfl INTEGER, k_sacks REAL, k_pressures INTEGER,
  k_pr_opp INTEGER, k_pr_wins INTEGER
);
CREATE INDEX ix_mart_idp_prospect_features_class ON mart_idp_prospect_features(draft_season, draft_position);
