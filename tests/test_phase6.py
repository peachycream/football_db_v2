"""Phase 6: read-time scoring, env rate formulas and ranking rules, the ported APIs. Offline."""
import json
import sqlite3
import unittest

from app import env as app_env
from fdb import env, scoring
from fdb.scoring import Rule, Scorer, catch_all_rules
from tests.helpers import TempEnv


class Rules(unittest.TestCase):
    def test_per_unit(self):
        self.assertAlmostEqual(Rule("-50-999", "*0.05").points(300), 15.0)

    def test_increment_truncates_and_never_goes_negative(self):
        r = Rule("-50-999", "5/300")
        self.assertEqual(r.points(299), 0)
        self.assertEqual(r.points(600), 10)
        self.assertEqual(r.points(-3), 0)      # floor(-3/300) = -1 once charged Miles Sanders -115

    def test_flat_needs_value_in_range_and_nonzero(self):
        r = Rule("300-999", "3")
        self.assertEqual(r.points(299), 0)
        self.assertEqual(r.points(300), 3)
        self.assertEqual(Rule("", "2").points(0), 0)

    def test_unparseable_range_is_unbounded(self):
        self.assertAlmostEqual(Rule("", "*1").points(-7), -7)


def _rules_conn(rows):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute('CREATE TABLE mart_mfl_rules (league_id, season, positions, event, "range", points)')
    c.executemany("INSERT INTO mart_mfl_rules VALUES ('L', 2025, ?, ?, ?, ?)", rows)
    return c


class CatchAll(unittest.TestCase):
    ALL = "QB|RB|WR|TE|DT|DE|LB|CB|S"

    def test_rules_naming_a_position_are_additive(self):
        c = _rules_conn([(self.ALL, "CC", "0-99", "*1"), ("TE", "CC", "0-99", "*0.5")])
        rules, season = catch_all_rules(c, "L")
        self.assertEqual(season, 2025)
        s = Scorer(["receptions"], rules=rules["TE"])
        self.assertAlmostEqual(s({"receptions": 6}), 9.0)       # 6*1 + 6*0.5 (TE premium ADDS)
        self.assertAlmostEqual(Scorer(["receptions"], rules=rules["WR"])({"receptions": 6}), 6.0)

    def test_narrow_only_event_does_not_score_other_positions(self):
        """RA rows name RB/WR/TE only: a QB's carries score nothing (Darnold 25.4 vs MFL 20.9)."""
        c = _rules_conn([("RB|WR|TE", "RA", "0-99", "*0.75"), (self.ALL, "RY", "-99-999", "*0.1")])
        rules, _ = catch_all_rules(c, "L")
        qb = Scorer(["carries", "rush_yards"], rules=rules["QB"])
        rb = Scorer(["carries", "rush_yards"], rules=rules["RB"])
        row = {"carries": 4, "rush_yards": 30}
        self.assertAlmostEqual(qb(row), 3.0)
        self.assertAlmostEqual(rb(row), 6.0)

    def test_multi_row_bonus_ladder_all_apply(self):
        """v1's UNIQUE(league, positions, event, range) collapsed these; v2 keeps every row."""
        c = _rules_conn([(self.ALL, "PY", "-50-999", "*0.04"), (self.ALL, "PY", "300-999", "3"),
                         (self.ALL, "PY", "-50-999", "10/500")])
        rules, _ = catch_all_rules(c, "L")
        self.assertAlmostEqual(Scorer(["pass_yards"], rules=rules["QB"])({"pass_yards": 310}), 12.4 + 3)

    def test_unscorable_columns_are_never_scored(self):
        s = Scorer(["fumbles", "sack_yards", "receptions"], ppr=scoring.PPR_POINTS)
        self.assertEqual(set(s.scored), {"receptions"})

    def test_kicker_house_default_only_when_asked(self):
        self.assertEqual(Scorer(["fg_made_50p"], rules={})({"fg_made_50p": 1}), 0)
        self.assertEqual(Scorer(["fg_made_50p"], rules={}, pk_default=True)({"fg_made_50p": 1}), 5.0)


class Ranking(unittest.TestCase):
    def test_ties_share_the_better_rank(self):
        self.assertEqual(app_env.pct_rank_of(0.2, [0.1, 0.2, 0.2, 0.3]), (75, 2, 4))

    def test_inverted_metric_ranks_low_first(self):
        pct, rank, n = app_env.pct_rank_of(0.1, [0.1, 0.2, 0.3], invert=True)
        self.assertEqual((rank, n), (1, 3))
        self.assertEqual(pct, 100)

    def test_small_sample_guard_withholds_rank(self):
        self.assertEqual(app_env._metric_obj(0.5, 7, [0.1, 0.5], False), {"v": 0.5, "pct": None, "n": 7})

    def test_none_is_never_ranked(self):
        self.assertEqual(app_env.pct_rank_of(None, [0.1]), (None, None, None))
        self.assertEqual(app_env.pct_rank_of(0.1, [None, 0.1, None])[2], 1)


class Formulas(unittest.TestCase):
    def test_offense_rates_are_ratios_of_sums(self):
        p = dict.fromkeys(env.OFF_COLS, 0)
        p.update(plays=10, dropbacks=6, epa_sum=1.0, xpass_sum=2.5, xpass_n=5, pace_sec_sum=300, pace_snap_n=10)
        m = app_env.off_metrics(p)
        self.assertAlmostEqual(m["epa_per_play"], 0.1)
        self.assertAlmostEqual(m["proe"], 0.6 - 0.5)
        self.assertAlmostEqual(m["sec_per_snap"], 30)
        self.assertIsNone(m["cpoe"])                     # 0 denominators are None, not 0

    def test_defense_missing_source_stays_null(self):
        """v1's rule: a stat whose source is absent (2026 FTN 4-man) must not rank first as 0."""
        row = dict.fromkeys(env.DEF_COLS)
        row.update(def_plays=60, dropbacks_faced=35, pressures=None, pass_rush_snaps=None,
                   pressures_4man_ftn=None, pass_rush_plays_4man_ftn=None)
        m = app_env.def_metrics(row)
        self.assertIsNone(m["pressure_rate"])
        self.assertIsNone(m["pressure_rate_4man_ftn"])

    def test_passer_rating_matches_nfl_formula(self):
        self.assertAlmostEqual(app_env._passer_rating(20, 20, 400, 5, 0), 158.33, places=2)   # perfect
        self.assertIsNone(app_env._passer_rating(0, 0, 0, 0, 0))

    def test_defensive_personnel_buckets(self):
        b = env._def_personnel_bucket
        self.assertEqual(b("4 DL, 2 LB, 5 DB"), "nickel")
        self.assertEqual(b("2 CB, 1 FS, 1 SS, 3 LB, 4 DL"), "base")
        self.assertEqual(b("3 CB, 1 FS, 1 SS, 1 S"), "dime")
        self.assertIsNone(b(None))
        self.assertIsNone(b("4 DL, 3 LB"))


class Apis(unittest.TestCase):
    """End-to-end on an empty, schema-applied DB: the ported routes answer (400/404),
    never 500, and the React shell carries the season context."""

    def setUp(self):
        self.t = TempEnv().__enter__()
        self.t.conn().close()
        from app import create_app
        self.c = create_app().test_client()

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_env_routes_validate_and_404_on_no_data(self):
        self.assertEqual(self.c.get("/api/team-offense-env").status_code, 400)
        self.assertEqual(self.c.get("/api/team-offense-env?season=2024&team=BUF").status_code, 404)
        self.assertEqual(self.c.get("/api/team-defense-env?season=2024&team=BUF").status_code, 404)
        self.assertEqual(self.c.get("/api/team-defense-env/gameday?season=2024&team=BUF").status_code, 404)

    def test_viz_shell_injects_season_ctx(self):
        r = self.c.get("/viz/offense")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("window.__SEASON_CTX__=", html)
        ctx = json.loads(html.split("window.__SEASON_CTX__=", 1)[1].split(";</script>", 1)[0])
        self.assertEqual(ctx, {})                       # empty DB: the bundle falls back, no 500
        self.assertEqual(self.c.get("/viz/scatter").status_code, 404)   # unported pages are not served


if __name__ == "__main__":
    unittest.main()
