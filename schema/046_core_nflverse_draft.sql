-- Phase 15a: IDP prospect model, bridge probe. Owners: registry/sources.toml.
-- nflverse draft_picks (release draft_picks/draft_picks.csv) and combine (release combine/combine.csv), columns verbatim.
-- Snapshot grain: the whole file every run. No primary key: the early draft years lack gsis_id/pfr ids; the loader's
-- checks refuse duplicate ids from 2016 on. The source column `to` (last NFL season) is NOT stored: it is a SQL keyword the
-- loader framework does not quote, and it is an outcome field the prospect model must never read. cfb_player_id / cfb_id is a Sports-Reference slug, NOT a CFBD or PFF id.
CREATE TABLE core_nflverse_draft_picks (
  season INTEGER NOT NULL,
  round INTEGER,
  pick INTEGER,
  team TEXT,
  gsis_id TEXT,
  pfr_player_id TEXT,
  cfb_player_id TEXT,
  pfr_player_name TEXT,
  hof TEXT,
  position TEXT,
  category TEXT,
  side TEXT,
  college TEXT,
  age INTEGER,
  allpro INTEGER,
  probowls INTEGER,
  seasons_started INTEGER,
  w_av INTEGER,
  car_av INTEGER,
  dr_av INTEGER,
  games INTEGER,
  pass_completions INTEGER,
  pass_attempts INTEGER,
  pass_yards INTEGER,
  pass_tds INTEGER,
  pass_ints INTEGER,
  rush_atts INTEGER,
  rush_yards INTEGER,
  rush_tds INTEGER,
  receptions INTEGER,
  rec_yards INTEGER,
  rec_tds INTEGER,
  def_solo_tackles INTEGER,
  def_ints INTEGER,
  def_sacks REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id)
);
CREATE INDEX ix_draft_picks_gsis ON core_nflverse_draft_picks (gsis_id);
CREATE INDEX ix_draft_picks_pfr ON core_nflverse_draft_picks (pfr_player_id);

CREATE TABLE core_nflverse_combine (
  season INTEGER NOT NULL,
  draft_year INTEGER,
  draft_team TEXT,
  draft_round INTEGER,
  draft_ovr INTEGER,
  pfr_id TEXT,
  cfb_id TEXT,
  player_name TEXT,
  pos TEXT,
  school TEXT,
  ht TEXT,
  wt INTEGER,
  forty REAL,
  bench INTEGER,
  vertical REAL,
  broad_jump INTEGER,
  cone REAL,
  shuttle REAL,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id)
);
CREATE INDEX ix_combine_pfr ON core_nflverse_combine (pfr_id);
