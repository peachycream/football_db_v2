-- Phase 11: the best scorer each team LEFT ON THE BENCH in a completed game, for the recap's commentary (FINAL only; NULL
-- otherwise, and NULL where the bench is empty). The player is joined through player_ids(mfl) like every other player in the
-- mart; an unresolved id has no name and the commentary falls back to its MFL id.
ALTER TABLE mart_matchup_card ADD COLUMN home_bench_best_name TEXT;
ALTER TABLE mart_matchup_card ADD COLUMN home_bench_best_pos TEXT;
ALTER TABLE mart_matchup_card ADD COLUMN home_bench_best_score REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_bench_best_name TEXT;
ALTER TABLE mart_matchup_card ADD COLUMN away_bench_best_pos TEXT;
ALTER TABLE mart_matchup_card ADD COLUMN away_bench_best_score REAL;
