-- Phase 17 (RAS): core_ras_maintable, loader `ras.maintable` (fdb/loaders/ras.py), raw staged by ops/ras_stage.py.
-- Source: the RAS Main Table (ras.football; Kent Lee Platte's Relative Athletic Score), drafted defenders of the 2016-2026 classes.
-- Field names are the site's column headers. `10YD`, `20YD` and `40YD` are stored as YD10, YD20 and YD40 because an identifier cannot
-- start with a digit (same numbers, same units). `POS` is the first position the site lists. RAS is the site's 0-10 percentile score
-- against every player at the position through the draft year; the splits and the forty are combine, or pro day when there is no combine.
-- There is NO unique key on (YEAR, PICK): the site lists 2016 pick 169 twice (a Lions LB and a Buccaneers CB). The bridge rejects both.
CREATE TABLE core_ras_maintable (
  YEAR INTEGER NOT NULL,
  PICK INTEGER NOT NULL,
  RD INTEGER,
  POS TEXT,
  RAS REAL,
  YD10 REAL,
  YD20 REAL,
  YD40 REAL,
  TEAM TEXT,
  load_id INTEGER
);
CREATE INDEX ix_core_ras_maintable_key ON core_ras_maintable(YEAR, PICK);
