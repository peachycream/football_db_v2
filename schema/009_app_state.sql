-- User-entered state (REBUILD_DESIGN §4): the only data NOT rebuildable from raw.
-- Owner: the app. `fdb rebuild` exports every app_* table to app_state/<table>.csv
-- (checked in) before building and re-imports it after.
--
-- Keyed on gsis_id. v1's draft_wishlist was keyed on v1 name slugs; the one-time
-- import (fdb/wishlist_import.py) re-keyed each slug by exact keys only.

CREATE TABLE app_wishlist (
  gsis_id         TEXT PRIMARY KEY,
  source_context  TEXT,
  note            TEXT,
  priority        INTEGER CHECK (priority IS NULL OR priority BETWEEN 1 AND 999),
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

-- Per-league priority. league_key = '<platform>:<league_id>' (e.g. 'mfl:30590').
CREATE TABLE app_wishlist_priority (
  gsis_id     TEXT NOT NULL REFERENCES app_wishlist(gsis_id) ON DELETE CASCADE,
  league_key  TEXT NOT NULL,
  priority    INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 999),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
  PRIMARY KEY (gsis_id, league_key)
);

-- The wishlist as the app shows it: joined to players (names) - reads only mart_*.
CREATE VIEW mart_wishlist AS
SELECT w.gsis_id AS player_key, w.gsis_id, w.source_context, w.note, w.priority, w.created_at,
       p.display_name AS name, p.position, p.latest_team AS team
FROM app_wishlist w LEFT JOIN players p ON p.gsis_id = w.gsis_id;

CREATE VIEW mart_wishlist_priority AS
SELECT gsis_id AS player_key, league_key, priority, updated_at FROM app_wishlist_priority;
