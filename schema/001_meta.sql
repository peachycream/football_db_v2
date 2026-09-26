-- Framework bookkeeping. Excluded from content hashes (fdb/db.py META_TABLES).

-- Rebuilt from data/raw/**/*.meta.json sidecars on every rebuild; the sidecars
-- are the durable manifest, this table is an index over them.
CREATE TABLE raw_fetch_log (
  path        TEXT PRIMARY KEY,          -- relative to data/raw
  source      TEXT NOT NULL,
  endpoint    TEXT NOT NULL,
  partition   TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  row_count   INTEGER NOT NULL,
  is_final    INTEGER NOT NULL CHECK (is_final IN (0, 1)),
  params      TEXT NOT NULL
);

-- One row per scope load. Core rows point back here through load_id.
CREATE TABLE load_log (
  load_id     INTEGER PRIMARY KEY,
  loader      TEXT NOT NULL,
  scope       TEXT NOT NULL,             -- e.g. 'season=2026' or 'season=2026/REG/week=3'
  raw_path    TEXT NOT NULL,
  raw_sha256  TEXT NOT NULL,
  rows_in     INTEGER NOT NULL,
  loaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
