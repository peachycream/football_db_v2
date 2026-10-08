-- Phase 11: the record, points for and best-lineup total INCLUDING the card's own week, for a FINAL card (a recap says where each team
-- stands now, not before the game). For a card whose week is not final these equal the "before this week" columns.
ALTER TABLE mart_matchup_card ADD COLUMN home_cur_w INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN home_cur_l INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN home_cur_t INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN home_cur_pf REAL;
ALTER TABLE mart_matchup_card ADD COLUMN home_cur_opt_pf REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_cur_w INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN away_cur_l INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN away_cur_t INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN away_cur_pf REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_cur_opt_pf REAL;
