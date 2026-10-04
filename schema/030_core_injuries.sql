-- Phase 12 (player status alerts, part A): the two injury feeds, the alert state the engine keeps, and the
-- views it reads. Probed live 2026-10-04.
--
-- core_nflverse_injuries: nflverse release injuries/injuries_<season>.csv = the NFL's own weekly injury report
-- (Wed/Thu/Fri practice status + the Friday game designation). gsis_id is the source's own. ONLY 2025+ is loaded:
-- 2016-2024 files have a different header (`date_modified`, no `season_type`), and alerts need the live season.
-- No per-row timestamp exists in 2025+, so this table says WHAT the status is, never WHEN it changed. A traded
-- player can appear for two teams in one week, so `team` is part of the key.
CREATE TABLE core_nflverse_injuries (
  season                    INTEGER NOT NULL,
  season_type               TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  game_type                 TEXT,
  team                      TEXT NOT NULL,
  week                      INTEGER NOT NULL,
  gsis_id                   TEXT NOT NULL,
  position                  TEXT,
  full_name                 TEXT,
  first_name                TEXT,
  last_name                 TEXT,
  report_primary_injury     TEXT,
  report_secondary_injury   TEXT,
  report_status             TEXT,        -- Out | Doubtful | Questionable | NULL (the game designation)
  practice_primary_injury   TEXT,
  practice_secondary_injury TEXT,
  practice_status           TEXT,        -- Full / Limited / Did Not Participate (source wording)
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, season_type, week, gsis_id, team)
);
CREATE INDEX ix_core_nflverse_injuries_gsis ON core_nflverse_injuries(gsis_id);

-- core_mfl_injuries: MFL export TYPE=injuries (league-independent, ~36 KB, no login), the CURRENT state only:
-- replaced whole on every load. `week` and `timestamp` are the response's own top-level fields, copied onto each
-- row under their own names; `season` is the URL's year (recorded in the raw sidecar so a rebuild gets the same).
-- Probed 2026-10-04: status in {IR, Out, Questionable, IR-R, IR-PUP, RETIRED, Suspended, IR-NFI, Holdout}; MFL has
-- no 'Doubtful'. exp_return is MFL's free-text estimate.
CREATE TABLE core_mfl_injuries (
  season      INTEGER NOT NULL,
  week        INTEGER NOT NULL,
  timestamp   INTEGER,                   -- epoch seconds the list was last built (MFL's)
  id          TEXT NOT NULL,             -- MFL player id
  status      TEXT NOT NULL,
  details     TEXT,
  exp_return  TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (season, id)
);

-- Alert state is the one thing here that is NOT rebuildable from raw (what was already pushed): app_* tables,
-- exported to app_state/*.csv and re-imported by `fdb rebuild`. Owner: alerts.engine (fdb/alerts.py).
-- One row per rostered player: the last status the engine recorded for them, as JSON, plus its signature.
CREATE TABLE app_alert_state (
  gsis_id       TEXT PRIMARY KEY,
  season        INTEGER NOT NULL,
  week          INTEGER NOT NULL,        -- the report week the status was read for
  signature     TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

-- Every alert the engine decided on, with whether the push went out. `ok` = 1 sent, 0 failed, NULL = recorded
-- without sending (--apply without --send).
CREATE TABLE app_alert_log (
  id        INTEGER PRIMARY KEY,
  logged_at TEXT NOT NULL,
  gsis_id   TEXT NOT NULL,
  kind      TEXT NOT NULL,               -- change | cleared | new
  title     TEXT NOT NULL,
  body      TEXT NOT NULL,
  ok        INTEGER,
  detail    TEXT
);

-- The two feeds renamed once for readers. They are kept apart on purpose: the NFL's report and MFL's list are
-- different claims (MFL carries IR/suspension; the NFL report carries practice participation), and merging them
-- is the reader's decision (fdb/alerts.py), made visible, never baked into a table.
CREATE VIEW mart_injury_nfl AS
SELECT season, season_type, week, team, gsis_id, position,
       report_status AS game_status,
       report_primary_injury AS game_injury, report_secondary_injury AS game_injury_2,
       practice_status,
       practice_primary_injury AS practice_injury, practice_secondary_injury AS practice_injury_2
FROM core_nflverse_injuries;

CREATE VIEW mart_injury_mfl AS
SELECT m.season, m.week, m.timestamp AS source_timestamp, pi.gsis_id, m.id AS mfl_id,
       m.status AS mfl_status, m.details AS mfl_details, m.exp_return AS mfl_exp_return
FROM core_mfl_injuries m
LEFT JOIN player_ids pi ON pi.source = 'mfl' AND pi.source_id = m.id;
