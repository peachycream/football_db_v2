"""Defense target-zone map (schema 058, fdb/def_zones.py): the view's filters and route join on minimal stand-in
source tables, then bands, shrinkage, league ratios, ranks and the filter behaviour on synthetic marts."""
import sqlite3
import unittest

from fdb import config, db as fdb_db
from fdb import def_zones as Z


def _view_conn():
    """Minimal source tables with only the columns the 058 views read, then the real 058 SQL."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE team_aliases (abbr TEXT, team TEXT, season_from INT, season_to INT, note TEXT);
    INSERT INTO team_aliases VALUES ('BLT','BAL',1999,9999,NULL),('SEA','SEA',1999,9999,NULL),('NE','NE',1999,9999,NULL);
    CREATE TABLE core_ftn_plays (season INT, season_type TEXT, week INT, pid INT, type TEXT, "off" TEXT, "def" TEXT,
        loc TEXT, trg TEXT, dot INT, comp INT, yds INT, td INT, td_type TEXT);
    CREATE TABLE core_ftn_participation (pid INT, skp1 TEXT, route1 TEXT, skp2 TEXT, route2 TEXT, skp3 TEXT, route3 TEXT,
        skp4 TEXT, route4 TEXT, skp5 TEXT, route5 TEXT);
    CREATE TABLE mart_player_week (season INT, season_type TEXT, week INT, gsis_id TEXT, position TEXT);
    CREATE TABLE core_player_stats (season INT, season_type TEXT, week INT, player_id TEXT, player_display_name TEXT);
    CREATE TABLE core_pbp (season INT, season_type TEXT, week INT, defteam TEXT, qb_dropback INT, epa REAL);
    """)
    sql = (config.SCHEMA_DIR / "058_mart_def_zones.sql").read_text()
    for stmt in fdb_db._split_sql(sql):
        c.execute(stmt)
    return c


def _play(c, pid, **kw):
    r = dict(season=2026, season_type="REG", week=1, pid=pid, type="PASS", off="NE", **{"def": "BLT"}, loc="SM",
             trg="p1", dot=8, comp=1, yds=12, td=0, td_type=None)
    r.update(kw)
    c.execute('INSERT INTO core_ftn_plays VALUES (:season,:season_type,:week,:pid,:type,:off,:def,:loc,:trg,:dot,:comp,:yds,:td,:td_type)', r)


class Views(unittest.TestCase):
    def setUp(self):
        self.c = _view_conn()
        c = self.c
        c.execute("INSERT INTO mart_player_week VALUES (2026,'REG',1,'p1','FB'),(2026,'REG',1,'p2','WR')")
        c.execute("INSERT INTO core_player_stats VALUES (2026,'REG',1,'p1','Pat One')")
        _play(c, 1)                                                   # kept; FB reads as RB; route joined from slot 2
        _play(c, 2, trg="p2", loc="DR", dot=31, comp=1, yds=40, td=1, td_type="REC")
        _play(c, 3, trg=None)                                         # no target: out
        _play(c, 4, loc=None)                                         # no lane: out
        _play(c, 5, type="RUSH")                                      # not a pass: out
        _play(c, 6, season_type="POST")                               # not REG: out
        _play(c, 7, td=1, td_type="INT")                              # pick-six is not a receiving TD
        c.execute("INSERT INTO core_ftn_participation VALUES (1,'zz','9 - Go','p1','3 - Hitch/Curl',NULL,NULL,NULL,NULL,NULL,NULL)")

    def test_filters_and_names(self):
        rows = self.c.execute("SELECT pid, defteam, offteam, position, lane, depth_tier, rec_td, route, name "
                              "FROM mart_def_target_play ORDER BY pid").fetchall()
        self.assertEqual([r["pid"] for r in rows], [1, 2, 7])
        self.assertEqual(rows[0]["defteam"], "BAL")                    # BLT -> BAL by team_aliases
        self.assertEqual((rows[0]["position"], rows[0]["lane"], rows[0]["depth_tier"]), ("RB", "M", "S"))
        self.assertEqual(rows[0]["route"], "3 - Hitch/Curl")           # the targeted player's slot, not slot 1
        self.assertEqual(rows[0]["name"], "Pat One")
        self.assertEqual((rows[1]["rec_td"], rows[1]["depth_tier"], rows[1]["route"]), (1, "D", None))
        self.assertEqual(rows[2]["rec_td"], 0)


def _mart(rows, weeks):
    """rows: (defteam, week, lane, air_yards, complete, yards, rec_td, position) -> in-memory marts."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE mart_def_target_play (season INT, week INT, defteam TEXT, lane TEXT, air_yards INT, complete INT,
        yards INT, rec_td INT, route TEXT, name TEXT, position TEXT, gsis_id TEXT);
    CREATE TABLE mart_def_dropback_week (season INT, season_type TEXT, week INT, defteam TEXT, dropbacks INT, epa REAL);""")
    for i, (tm, wk, lane, ay, comp, yds, td, pos) in enumerate(rows):
        c.execute("INSERT INTO mart_def_target_play VALUES (2026,?,?,?,?,?,?,?,NULL,?,?,?)",
                  (wk, tm, lane, ay, comp, yds, td, f"n{i}", pos, f"g{i}"))
    for tm in ("AAA", "BBB", "CCC"):
        for wk in weeks:
            c.execute("INSERT INTO mart_def_dropback_week VALUES (2026,'REG',?,?,35,?)", (wk, tm, 1.0 if tm == "AAA" else -1.0))
    return c


ROWS = ([("AAA", w, "L", 3, 1, 10, 0, "WR") for w in (1, 2)] + [("AAA", 1, "M", 25, 0, 0, 0, "TE")] +
        [("BBB", w, "L", 3, 1, 8, 0, "WR") for w in (1, 2)] + [("BBB", 2, "R", -2, 1, 5, 0, "RB")] +
        [("CCC", 1, "L", 12, 0, 0, 0, "WR"), ("CCC", 2, "L", 12, 1, 20, 1, "WR")])


class Build(unittest.TestCase):
    def setUp(self):
        self.c = _mart(ROWS, (1, 2))

    def test_bands(self):
        self.assertEqual([Z.band_of(a) for a in (-9, -1, 0, 4, 5, 9, 10, 14, 15, 19, 20, 29, 30, 55)],
                         [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6])

    def test_cells_sum_to_filtered_targets_and_league_is_the_sum_of_teams(self):
        d = Z.build(self.c, "AAA", "ALL")
        self.assertEqual(sum(x["n"] for x in d["cells"]), d["targets"])
        self.assertEqual(d["targets"], 3)
        self.assertEqual(Z.build(self.c, "AAA", "WR")["targets"], 2)         # position filter
        self.assertEqual(Z.build(self.c, "AAA", "RB")["targets"], 0)

    def test_window_uses_last_n_weeks(self):
        d = Z.build(self.c, "AAA", "ALL", 1)
        self.assertEqual(d["weeks"], [2, 2])
        self.assertEqual(d["targets"], 1)
        self.assertEqual(d["games"], 1)

    def test_ratio_is_shrunk_toward_one_and_exact_for_the_formula(self):
        d = Z.build(self.c, "AAA", "ALL")
        cell = next(x for x in d["cells"] if x["lane"] == "L" and x["label"] == "0-4")
        # AAA: 2 targets in 2 games; league: 4 targets in this cell (AAA 2 + BBB 2) over 6 team-games
        raw = (2 / 2) / (4 / 6)
        self.assertAlmostEqual(cell["ratio"]["targets"], 1 + (raw - 1) * 2 / (2 + Z.SHRINK_K), places=9)
        empty = next(x for x in d["cells"] if x["lane"] == "R" and x["label"] == "30+")
        self.assertEqual((empty["n"], empty["ratio"]["targets"]), (0, 1.0))

    def test_completion_pct_is_a_ratio_of_sums(self):
        d = Z.build(self.c, "CCC", "WR")
        cell = next(x for x in d["cells"] if x["lane"] == "L" and x["label"] == "10-14")
        self.assertEqual((cell["n"], cell["c"]), (2, 1))                     # 50%, from counts

    def test_ppr_points_and_rank(self):
        d = Z.build(self.c, "CCC", "ALL")
        # CCC: one catch for 20 yds + a TD = 1 + 2 + 6 = 9 points over 2 games
        self.assertAlmostEqual(d["pts"]["value"], 4.5)
        self.assertEqual(d["pts"]["of"], 3)
        self.assertEqual(Z.build(self.c, "AAA", "ALL")["pts"]["rank"], 3)      # AAA 2.0 < BBB 2.55 < CCC 4.5 per game
        self.assertEqual(Z._rank({"a": 3, "b": 1, "c": 2}, "a"), (1, 3, 100.0))
        self.assertEqual(Z._rank({"a": 3, "b": 1, "c": 2}, "b"), (3, 3, 0.0))

    def test_epa_strip_uses_all_dropbacks(self):
        d = Z.build(self.c, "AAA", "RB")
        epa = next(s for s in d["strips"] if s["key"] == "epa")
        self.assertAlmostEqual(epa["value"], 2.0 / 70)                       # epa SUM over dropbacks, 2 weeks x 35
        self.assertEqual(epa["rank"], 1)

    def test_unknown_team(self):
        self.assertIn("error", Z.build(self.c, "ZZZ", "ALL"))


if __name__ == "__main__":
    unittest.main()
