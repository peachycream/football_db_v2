-- Phase 11: a third post MODE, 'live' (the "so far" card of the week in progress), alongside 'recap' and 'preview'. SQLite cannot change
-- a CHECK constraint, so the table is rebuilt with every column and row carried over unchanged (app_post_log is outward-facing
-- history exported to app_state/app_post_log.csv by `fdb rebuild`; nothing about it changes except the allowed modes).
CREATE TABLE app_post_log_new (
  league_id   TEXT NOT NULL,
  season      INTEGER NOT NULL,
  week        INTEGER NOT NULL,
  mode        TEXT NOT NULL CHECK (mode IN ('recap', 'preview', 'live')),
  status      TEXT NOT NULL CHECK (status IN ('sending', 'posted', 'failed')),
  claimed_at  TEXT NOT NULL,
  posted_at   TEXT,
  message_id  TEXT,
  png_sha256  TEXT,
  home_id     TEXT,
  away_id     TEXT,
  detail      TEXT,
  parts_total INTEGER,
  parts_posted INTEGER NOT NULL DEFAULT 0,
  message_ids TEXT,
  PRIMARY KEY (league_id, season, week, mode)
);
INSERT INTO app_post_log_new (league_id, season, week, mode, status, claimed_at, posted_at, message_id, png_sha256, home_id, away_id,
                              detail, parts_total, parts_posted, message_ids)
  SELECT league_id, season, week, mode, status, claimed_at, posted_at, message_id, png_sha256, home_id, away_id,
         detail, parts_total, parts_posted, message_ids FROM app_post_log;
DROP TABLE app_post_log;
ALTER TABLE app_post_log_new RENAME TO app_post_log;
