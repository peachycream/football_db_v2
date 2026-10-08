-- Phase 11: points for is now PER GAME (a franchise that plays two games a week counts both, which is what the league's own
-- standings and power rankings do and what the W-L record already did), the best possible lineup total over the same games
-- (so lineup efficiency = pf / opt_pf is computed at read time), and each team's conference for conference rankings.
-- opt_pf is NULL when any completed game lacks an optimal-lineup figure. Rebuilt by the matchup builder, so no backfill.
ALTER TABLE mart_matchup_card ADD COLUMN home_opt_pf REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_opt_pf REAL;
ALTER TABLE mart_matchup_card ADD COLUMN home_conference TEXT;
ALTER TABLE mart_matchup_card ADD COLUMN away_conference TEXT;
