-- Route tree (Player Dashboard /routes; Turon 2026-10-01: "route tree data is missing").
-- One row per player-week-route from FTN participation: every skill player's route on every
-- play that counted (route1..5 for skp1..5; FTN charts routes from 2026 - its 2021-2025 route
-- columns are empty), joined to the play for the target / catch / yards. Built by `dashboard.build`.
-- 'Counted' = FTN type PASS or RUSH (a route run on a play that became a scramble is a route);
-- no-plays are excluded. Against PFF routes, 2026 wk1-3, 147 receivers with >=40: median 0.964,
-- p10-p90 0.92-1.02 (PASS only: median 0.909; with no-plays: 1.022 and wider).
-- COUNTS ONLY: share, TPRR, YPRR are computed at read time. Verified 2026 wk1-3 against
-- nflverse: same 346 targeted players; targets exact for 334 (all within 1), receptions exact
-- for all, receiving yards within 2 for 343.
CREATE TABLE mart_player_routes_week (
  season       INTEGER NOT NULL,
  season_type  TEXT    NOT NULL,
  week         INTEGER NOT NULL,
  gsis_id      TEXT    NOT NULL,
  route        TEXT    NOT NULL,   -- FTN's label verbatim, e.g. '3 - Hitch/Curl'
  routes       INTEGER NOT NULL,   -- counted plays on which he ran this route
  targets      INTEGER NOT NULL,   -- ... and was the targeted receiver
  receptions   INTEGER NOT NULL,
  rec_yards    INTEGER NOT NULL,
  PRIMARY KEY (season, season_type, week, gsis_id, route)
);
CREATE INDEX ix_mart_player_routes_week_player ON mart_player_routes_week(gsis_id, season);
