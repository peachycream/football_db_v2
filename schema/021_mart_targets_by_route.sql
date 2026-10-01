-- Targets by route, 2016-2025 (Turon 2026-10-01): the route-tree history for seasons FTN did not
-- chart routes for. nflverse participation's `route` is the route of the TARGETED receiver only
-- (NGS), so this is a TARGET tree, not a route tree: there is no routes-run denominator, and the
-- page says so. Route names are verbatim and change in 2023 (2016-2022: FLAT/CROSS/HITCH/IN/OUT/
-- ANGLE...; 2023-: QUICK OUT/DEEP OUT/IN/DIG/HITCH/CURL/SHALLOW CROSS/DRAG...), so a season shows its
-- own vocabulary; nothing is mapped across (OUT split into QUICK/DEEP OUT; CROSS is not DRAG).
-- Coverage: a route on 98.6-99.9% of targets every season (checked in dashboard.build).
CREATE TABLE mart_player_targets_by_route_week (
  season       INTEGER NOT NULL,
  season_type  TEXT    NOT NULL,
  week         INTEGER NOT NULL,
  gsis_id      TEXT    NOT NULL,   -- pbp receiver_player_id
  route        TEXT    NOT NULL,   -- nflverse participation `route`, verbatim
  targets      INTEGER NOT NULL,
  receptions   INTEGER NOT NULL,
  rec_yards    REAL    NOT NULL,   -- pbp yards_gained on his completions
  PRIMARY KEY (season, season_type, week, gsis_id, route)
);
CREATE INDEX ix_mart_targets_by_route_player ON mart_player_targets_by_route_week(gsis_id, season);
