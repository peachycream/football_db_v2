-- Phase 13 (game-day inactives and pre-kickoff polling): ESPN's league-wide injuries feed, plus the table that
-- remembers which "final check" pushes already went out. Probed live 2026-10-04 (Week 4 Sunday slate).
--
-- core_espn_injuries: site.api.espn.com/apis/site/v2/sports/football/nfl/injuries, ONE call for all 32 teams
-- (~800 entries; 8.7 MB raw, 348 KB gzipped, 0.25 s). It is the only free source seen that carries a TIME per entry
-- and the game-day word: 'Out' + fantasyStatus INACTIVE is the posted inactive list, and 'Active' with a comment
-- "is active for Sunday's ..." is a confirmation. Measured on 28 teams: those entries first appear 70-89 minutes
-- before kickoff (one outlier 245) and keep arriving until ~17-20 minutes before.
-- The per-game /summary endpoint was rejected: it caps every team at 5 entries.
--
-- Current state only: replaced whole on every load. ESPN's own player id exists only inside the player-card link
-- (athlete.links[].href .../player/_/id/<id>/...): `athlete.id` is absent on all 800 entries and the entry-level `id`
-- is a NEWS id (negative for unlisted players), so neither is used. The loader takes the id from the link, and refuses
-- the payload if an entry yields zero or two ids. 798 of 800 resolved through player_ids(source='espn').
-- Only regular season (2) and postseason (3) are loaded; a preseason/offseason feed is refused (rule 5).
-- Status vocabulary seen: Active, Out, Injured Reserve, Questionable, Doubtful. New words are stored as sent.
CREATE TABLE core_espn_injuries (
  season                INTEGER NOT NULL,
  season_type           TEXT NOT NULL CHECK (season_type IN ('REG', 'POST')),
  timestamp             TEXT,           -- the response's own top-level time (when ESPN built the list)
  espn_player_id        TEXT NOT NULL,  -- from the player-card link; see above
  team                  TEXT NOT NULL,  -- athlete.team.abbreviation as ESPN spells it (WSH, LAR)
  position              TEXT,           -- athlete.position.abbreviation
  status                TEXT NOT NULL,
  date                  TEXT NOT NULL,  -- when ESPN last changed this entry, 'YYYY-MM-DDTHH:MMZ' (UTC)
  shortComment          TEXT,
  longComment           TEXT,
  details_fantasyStatus TEXT,           -- INACTIVE | QUESTIONABLE | OUT | DOUBTFUL | IR | IR-R | PUP-R | NULL
  details_type          TEXT,
  details_location      TEXT,
  details_detail        TEXT,
  details_side          TEXT,
  details_returnDate    TEXT,
  load_id INTEGER NOT NULL REFERENCES load_log(load_id),
  PRIMARY KEY (espn_player_id)
);
CREATE INDEX ix_core_espn_injuries_team ON core_espn_injuries(team);

-- App state: one row per (player, game) whose "NOT CONFIRMED, kickoff in 15 minutes" push was decided, so it goes out
-- once. ok = 1 sent, 0 failed (retried while the game has not kicked off), NULL never used. Owner: alerts.engine.
CREATE TABLE app_alert_final (
  gsis_id  TEXT NOT NULL,
  game_id  TEXT NOT NULL,
  sent_at  TEXT NOT NULL,
  ok       INTEGER NOT NULL,
  PRIMARY KEY (gsis_id, game_id)
);

CREATE VIEW mart_injury_espn AS
SELECT e.season, e.season_type, e.timestamp AS feed_timestamp, pi.gsis_id, e.espn_player_id, e.team AS espn_team,
       e.position AS espn_position, e.status AS espn_status, e.date AS espn_date,
       e.details_fantasyStatus AS espn_fantasy_status, e.details_type AS espn_injury, e.details_returnDate AS espn_return_date,
       e.shortComment AS espn_comment
FROM core_espn_injuries e
LEFT JOIN player_ids pi ON pi.source = 'espn' AND pi.source_id = e.espn_player_id;
