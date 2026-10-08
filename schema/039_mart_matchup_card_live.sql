-- Phase 11: the "so far" card. For a week IN PROGRESS the mart carries the NEWEST liveScoring snapshot (core_mfl_live_scores /
-- core_mfl_live_players): each side's points so far and how many starters have yet to play or are playing. NULL for a FINAL
-- card, and for a card with no live snapshot. The points-so-far of each starter are in mart_matchup_card_players.actual and
-- mart_matchup_card_groups.actual for such a card (a FINAL card has the final numbers there).
ALTER TABLE mart_matchup_card ADD COLUMN live_snapshot_at TEXT;
ALTER TABLE mart_matchup_card ADD COLUMN home_live_score REAL;
ALTER TABLE mart_matchup_card ADD COLUMN away_live_score REAL;
ALTER TABLE mart_matchup_card ADD COLUMN home_live_yet INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN away_live_yet INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN home_live_playing INTEGER;
ALTER TABLE mart_matchup_card ADD COLUMN away_live_playing INTEGER;
