-- Reference data, owned by this schema file (registry owner 'schema').
-- `team` is the CURRENT franchise abbreviation (nflverse spelling).
CREATE TABLE teams (
  team        TEXT PRIMARY KEY,
  conference  TEXT NOT NULL CHECK (conference IN ('AFC', 'NFC')),
  division    TEXT NOT NULL CHECK (division IN ('East', 'North', 'South', 'West'))
);

INSERT INTO teams (team, conference, division) VALUES
 ('BUF','AFC','East'),('MIA','AFC','East'),('NE','AFC','East'),('NYJ','AFC','East'),
 ('BAL','AFC','North'),('CIN','AFC','North'),('CLE','AFC','North'),('PIT','AFC','North'),
 ('HOU','AFC','South'),('IND','AFC','South'),('JAX','AFC','South'),('TEN','AFC','South'),
 ('DEN','AFC','West'),('KC','AFC','West'),('LV','AFC','West'),('LAC','AFC','West'),
 ('DAL','NFC','East'),('NYG','NFC','East'),('PHI','NFC','East'),('WAS','NFC','East'),
 ('CHI','NFC','North'),('DET','NFC','North'),('GB','NFC','North'),('MIN','NFC','North'),
 ('ATL','NFC','South'),('CAR','NFC','South'),('NO','NFC','South'),('TB','NFC','South'),
 ('ARI','NFC','West'),('LA','NFC','West'),('SF','NFC','West'),('SEA','NFC','West');

-- Every spelling any source uses, mapped to the franchise. Core tables keep the
-- source's own value; marts join through this table. A team value that is not
-- here fails the loading check instead of silently dropping out of a join.
CREATE TABLE team_aliases (
  abbr        TEXT NOT NULL,
  team        TEXT NOT NULL REFERENCES teams(team),
  season_from INTEGER NOT NULL DEFAULT 1999,
  season_to   INTEGER NOT NULL DEFAULT 9999,
  note        TEXT,
  PRIMARY KEY (abbr, season_from)
);

INSERT INTO team_aliases (abbr, team) SELECT team, team FROM teams;
INSERT INTO team_aliases (abbr, team, season_from, season_to, note) VALUES
 ('OAK','LV',1999,2019,'Raiders in Oakland through 2019'),
 ('SD','LAC',1999,2016,'Chargers in San Diego through 2016'),
 ('STL','LA',1999,2015,'Rams in St. Louis through 2015'),
 ('LAR','LA',1999,9999,'PFR/PFF spelling'),
 ('LVR','LV',1999,9999,'PFR spelling'),
 ('JAC','JAX',1999,9999,'legacy spelling'),
 ('WSH','WAS',1999,9999,'ESPN spelling'),
 ('ARZ','ARI',1999,9999,'PFF spelling'),
 ('BLT','BAL',1999,9999,'PFF spelling'),
 ('CLV','CLE',1999,9999,'PFF spelling'),
 ('HST','HOU',1999,9999,'PFF spelling');
