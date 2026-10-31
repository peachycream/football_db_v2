-- Phase 15e-2 (PHASE15E2_SPEC.md): Blocks C and D of the IDP prospect features mart. Builder `idp_prospect.features` (fdb/idp_prospect.py).
--
-- The draft table spells six team codes the PFR way (GNB KAN NOR NWE SFO TAM); team_aliases already covers the PFF spellings and the
-- relocations. These six are exact three-letter codes, added so the join to the NFL side is exact (a code that is still not here fails
-- the build, nothing is matched fuzzily).
INSERT INTO team_aliases (abbr, team, season_from, season_to, note) VALUES
 ('GNB','GB',1999,9999,'PFR spelling'),
 ('KAN','KC',1999,9999,'PFR spelling'),
 ('NOR','NO',1999,9999,'PFR spelling'),
 ('NWE','NE',1999,9999,'PFR spelling'),
 ('SFO','SF',1999,9999,'PFR spelling'),
 ('TAM','TB',1999,9999,'PFR spelling');

-- Block C, trajectory: the college season BEFORE college_season (NULL when the player has no row for it). Counts and grades as given.
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_season INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_games INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_snaps_defense INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_tackles INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_tfl INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_sacks REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_stops INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_pressures INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_grade_defense REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_grade_run_defense REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_grade_coverage REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_grade_pass_rush REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_grade_tackle REAL;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_pr_opp INTEGER;
ALTER TABLE mart_idp_prospect_features ADD COLUMN p_pr_wins INTEGER;

-- Block D, landing spot: the drafting team's REGULAR SEASON of draft_season - 1 at the player's NFL group (DT/EDGE/LB/CB/S from
-- nfl_pff_position). Known on draft day; no number from the draft year onward.
-- canonical team code via team_aliases
ALTER TABLE mart_idp_prospect_features ADD COLUMN draft_team TEXT;
-- defensive snaps by that team's players at that group
ALTER TABLE mart_idp_prospect_features ADD COLUMN t_group_snaps_prev INTEGER;
-- its players at that group with >= 300 snaps there
ALTER TABLE mart_idp_prospect_features ADD COLUMN t_group_players_prev INTEGER;
