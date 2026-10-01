-- DD Fantasy Football Trinity (owner per table: registry/sources.toml). Client: fdb/ddff.py.
-- Source columns keep the source's own names. Framework columns: season, season_type, week.
-- Seasons 2021+ and REG weeks 1-17 only: where the site's own pickers start and stop.

-- One row per player-week: the FTN counts DD's Trinity Score is computed from. Counts only; the score is
-- NOT a stored source field for a week (the site computes it in the browser: see mart_trinity_*).
-- DD's own gsis id is on every row; sleeper_id is NULL on 24 rows in 2021-2023 (Mike Strachan et al.), so the gsis id is the key.
-- The mart resolves gsis_id through player_ids by sleeper_id where there is one.
CREATE TABLE core_trinity_ftn_aggregates (
  season INTEGER NOT NULL,
  season_type TEXT NOT NULL CHECK (season_type = 'REG'),
  week INTEGER NOT NULL CHECK (week BETWEEN 1 AND 17),
  player_gsis_id TEXT NOT NULL,
  full_name TEXT,
  pos TEXT NOT NULL,
  sleeper_id TEXT,
  team TEXT NOT NULL,
  games INTEGER,
  routes INTEGER,
  targets INTEGER,
  rec INTEGER,
  rec_yards INTEGER,
  yac REAL,
  rec_td INTEGER,
  first_downs INTEGER,
  player_air_yards REAL,
  team_air_yards REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, season_type, week, player_gsis_id)
);
CREATE INDEX ix_trinity_agg_sleeper ON core_trinity_ftn_aggregates(sleeper_id, season);

-- DD's own stored season-long score (closed seasons), VERBATIM. DD builds it by NAME: the same Sleeper id can
-- sit on two rows ("Tank Dell" / "Nathaniel Dell", 6 such ids in 2023, 5 in 2024) and a few rows have no id, so
-- sleeper_id is neither key nor unique here and nothing is repaired. (player_name, position, team) is unique in
-- every season, so that is the row identity. The mart only compares against ids that appear once.
CREATE TABLE core_trinity_scores (
  season INTEGER NOT NULL,
  season_type TEXT NOT NULL CHECK (season_type = 'REG'),
  player_name TEXT NOT NULL,
  position TEXT NOT NULL,
  team TEXT NOT NULL,
  sleeper_id TEXT,
  trinity_score REAL NOT NULL,
  ppg REAL,
  games INTEGER,
  tier TEXT,
  rank INTEGER,
  first_downs REAL,
  yprr REAL,
  yac_per_game REAL,
  rec_per_game REAL,
  air_yard_share REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, season_type, player_name, position, team)
);
CREATE INDEX ix_trinity_scores_sleeper ON core_trinity_scores(sleeper_id, season);

-- Trinity Score as the site's page computes it (fdb/trinity.py ports that function): a derived
-- table, not a source field. mart_trinity_week = the one-week window; mart_trinity_through_week =
-- weeks 1..week summed (season to date). Same columns. gsis_id is joined through player_ids
-- (source 'sleeper'); NULL where unresolved, never guessed. player_gsis_id is DD's own, kept to
-- audit the join. z_* are the five clamped z-scores behind the score.
CREATE TABLE mart_trinity_week (
  season INTEGER NOT NULL,
  season_type TEXT NOT NULL,
  week INTEGER NOT NULL,
  sleeper_id TEXT,
  player_gsis_id TEXT NOT NULL,
  gsis_id TEXT,
  full_name TEXT,
  team TEXT NOT NULL,
  position TEXT NOT NULL,
  games INTEGER NOT NULL,
  routes INTEGER NOT NULL,
  targets INTEGER NOT NULL,
  rec INTEGER NOT NULL,
  rec_yards INTEGER NOT NULL,
  rec_td INTEGER NOT NULL,
  first_downs INTEGER NOT NULL,
  yprr REAL NOT NULL,
  rec_per_game REAL NOT NULL,
  yac_per_game REAL NOT NULL,
  air_yard_share REAL NOT NULL,
  z_first_downs REAL NOT NULL,
  z_yprr REAL NOT NULL,
  z_yac_per_game REAL NOT NULL,
  z_rec_per_game REAL NOT NULL,
  z_air_yard_share REAL NOT NULL,
  trinity_score REAL NOT NULL,
  tier TEXT NOT NULL,
  position_rank INTEGER NOT NULL,
  PRIMARY KEY (season, season_type, week, player_gsis_id)
);
CREATE INDEX ix_mart_trinity_week_gsis ON mart_trinity_week(gsis_id, season);

CREATE TABLE mart_trinity_through_week (
  season INTEGER NOT NULL,
  season_type TEXT NOT NULL,
  week INTEGER NOT NULL,
  sleeper_id TEXT,
  player_gsis_id TEXT NOT NULL,
  gsis_id TEXT,
  full_name TEXT,
  team TEXT NOT NULL,
  position TEXT NOT NULL,
  games INTEGER NOT NULL,
  routes INTEGER NOT NULL,
  targets INTEGER NOT NULL,
  rec INTEGER NOT NULL,
  rec_yards INTEGER NOT NULL,
  rec_td INTEGER NOT NULL,
  first_downs INTEGER NOT NULL,
  yprr REAL NOT NULL,
  rec_per_game REAL NOT NULL,
  yac_per_game REAL NOT NULL,
  air_yard_share REAL NOT NULL,
  z_first_downs REAL NOT NULL,
  z_yprr REAL NOT NULL,
  z_yac_per_game REAL NOT NULL,
  z_rec_per_game REAL NOT NULL,
  z_air_yard_share REAL NOT NULL,
  trinity_score REAL NOT NULL,
  tier TEXT NOT NULL,
  position_rank INTEGER NOT NULL,
  PRIMARY KEY (season, season_type, week, player_gsis_id)
);
CREATE INDEX ix_mart_trinity_thru_gsis ON mart_trinity_through_week(gsis_id, season);
