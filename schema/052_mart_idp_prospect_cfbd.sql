-- Phase 15e-3 (PHASE15E3_SPEC.md): the CFBD bridge and the new feature columns. Builders `idp_prospect.cfbd_bridge` then
-- `idp_prospect.features` (fdb/idp_cfbd.py, fdb/idp_prospect.py).
--
-- One bridge row per drafted defender 2017+ (core_nflverse_draft_picks side D, exact gsis_id). The CFBD athlete id comes from
-- CFBD /draft/picks joined to the nflverse draft table on (season, overall pick), nothing else. A team contradiction (the CFBD
-- drafting team is not the nflverse team) REJECTS the pair: every CFBD column is then NULL and the status says why. A name is
-- never used to select anything. The recruit joins through core_cfbd_roster.recruitIds of the athlete's rows up to draft year - 1.
CREATE TABLE mart_idp_prospect_cfbd_bridge (
  gsis_id TEXT NOT NULL PRIMARY KEY,
  draft_season INTEGER NOT NULL,
  draft_pick INTEGER NOT NULL,
  cfbd_athlete_id TEXT,
  draft_status TEXT NOT NULL,        -- ok | no_cfbd_pick | no_athlete_id | team_contradiction
  dp_pre_rank INTEGER,               -- CFBD preDraftRanking
  dp_pre_pos_rank INTEGER,           -- CFBD preDraftPositionRanking
  dp_pre_grade INTEGER,              -- CFBD preDraftGrade
  recruit_id TEXT,
  recruit_status TEXT NOT NULL,      -- ok | no_bridge | no_roster_recruit_id | multi_recruit_id | recruit_not_loaded | athlete_disagrees
  rec_year INTEGER,                  -- recruiting class
  rec_stars INTEGER,
  rec_rating REAL,
  rec_ranking INTEGER
);
CREATE INDEX ix_mart_idp_prospect_cfbd_bridge_class ON mart_idp_prospect_cfbd_bridge(draft_season);

-- Blocks E, F and G in the features mart, copied from the bridge (E, F) and read from core_cfbd_player_season (G).
-- NULL stays NULL; has_recruit and has_cfbd_stats carry the missingness. Reach (draft pick minus dp_pre_rank) and per-game rates are read-time.
ALTER TABLE mart_idp_prospect_features ADD COLUMN cfbd_athlete_id TEXT;
ALTER TABLE mart_idp_prospect_features ADD COLUMN dp_pre_rank INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN dp_pre_pos_rank INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN dp_pre_grade INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN has_recruit INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN rec_year INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN rec_stars INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN rec_rating REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN rec_ranking INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN has_cfbd_stats INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN cf_tackles REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN cf_tfl REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN cf_sacks REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN cf_hurries REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN cf_pd REAL;
