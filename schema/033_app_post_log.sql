-- Phase 11: the Matchup of the Week post log (fdb/discord_post.py). One row per league, season, week and MODE (recap or
-- preview): at most one post for each, ever, unless a human passes --repost.
--
-- This is OUTWARD-FACING HISTORY, not rebuildable data: Discord is the only other copy. So it is an app_* table, which
-- `fdb rebuild` exports to app_state/app_post_log.csv and re-imports. (Numbered 033 on purpose: 030 and 031 belong to the
-- injuries/alerts work and 032 is left free for it.)
--
--   status  sending  claimed BEFORE the request is made. A crash between the claim and the answer leaves this, and the
--                    message MAY have been delivered, so a later run refuses and tells a human to look at the channel.
--           posted   Discord answered 2xx (message_id is Discord's id for it, for deleting a wrong post).
--           failed   a definite failure (HTTP error or no connection). Safe to retry; the next run does so by itself.
-- png_sha256 identifies the exact image that was sent.
CREATE TABLE app_post_log (
  league_id   TEXT NOT NULL,
  season      INTEGER NOT NULL,
  week        INTEGER NOT NULL,
  mode        TEXT NOT NULL CHECK (mode IN ('recap', 'preview')),
  status      TEXT NOT NULL CHECK (status IN ('sending', 'posted', 'failed')),
  claimed_at  TEXT NOT NULL,
  posted_at   TEXT,
  message_id  TEXT,
  png_sha256  TEXT,
  home_id     TEXT,
  away_id     TEXT,
  detail      TEXT,
  PRIMARY KEY (league_id, season, week, mode)
);
