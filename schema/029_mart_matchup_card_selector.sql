-- Phase 11: the inputs v1's featured-game selector needs (fdb/matchup_pick.py), appended to mart_matchup_card.
--   is_playoff           the fantasy week is after lastRegularSeasonWeek (a bracket week, not a regular-season game)
--   *_strength           the sum of the WHOLE lineup's projections (starters and bench) from the pre-kickoff
--                        snapshot, v1's "strength"; NULL without one (nothing is guessed)
--   *_roster_actual      FINAL only: the sum of every lineup player's actual score, starters and bench, so a
--                        completed week with no pre-kickoff projection can still be ranked from what happened
ALTER TABLE mart_matchup_card ADD COLUMN is_playoff INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mart_matchup_card ADD COLUMN home_strength REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_strength REAL;
ALTER TABLE mart_matchup_card ADD COLUMN home_roster_actual REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_roster_actual REAL;
