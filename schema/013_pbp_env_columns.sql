-- Phase 6: four more nflverse pbp columns the team-environment marts need
-- (drive result/length, TFL and forced fumbles for havoc). Source names verbatim;
-- the loader fills them on the next load from the raw files already on disk.
ALTER TABLE core_pbp ADD COLUMN fixed_drive_result TEXT;
ALTER TABLE core_pbp ADD COLUMN drive_play_count INTEGER;
ALTER TABLE core_pbp ADD COLUMN tackled_for_loss INTEGER;
ALTER TABLE core_pbp ADD COLUMN fumble_forced INTEGER;
