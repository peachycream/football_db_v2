-- Phase 17 (RAS): the bridge and the new feature columns. Builders `idp_prospect.ras_bridge` then `idp_prospect.features`
-- (fdb/idp_ras.py, fdb/idp_prospect.py).
--
-- One bridge row per drafted defender 2017+ (core_nflverse_draft_picks side D, exact gsis_id). The RAS row is found by
-- (draft year, overall pick) and nothing else. REJECTED pairs leave every RAS column NULL and the status says why:
--   duplicate_key       the site lists that (year, pick) more than once
--   team_contradiction  the site's team is not the drafting team of the nflverse table (a fixed 32-nickname table)
--   side_contradiction  the site's position is in the secondary and the draft table's is in the front seven, or the reverse
-- A name is never read; a position or team may only reject, never select.
CREATE TABLE mart_idp_prospect_ras_bridge (
  gsis_id TEXT NOT NULL PRIMARY KEY,
  draft_season INTEGER NOT NULL,
  draft_pick INTEGER NOT NULL,
  ras_status TEXT NOT NULL,          -- ok | no_ras_row | duplicate_key | team_contradiction | side_contradiction
  ras REAL,                          -- the site's 0-10 score, NULL when the site shows none (fewer than 6 measurables)
  ras_yd10 REAL,
  ras_yd20 REAL,
  ras_yd40 REAL,
  ras_pos TEXT
);
CREATE INDEX ix_mart_idp_prospect_ras_bridge_class ON mart_idp_prospect_ras_bridge(draft_season);

-- Copied from the bridge; NULL stays NULL, has_ras is 1 only for an accepted pair. The 10-yard split and the forty are combine, or pro day
-- when there was no combine (the combine-only columns forty/vertical/... are unchanged).
ALTER TABLE mart_idp_prospect_features ADD COLUMN has_ras INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN ras REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN ras_yd10 REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN ras_yd20 REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN ras_yd40 REAL;
