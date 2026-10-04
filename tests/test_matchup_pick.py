"""Phase 11: the featured-game picker (fdb/matchup_pick.py), a port of v1's `pick_matchup` scorer, and the mart columns
it needs. The formula test is HAND-COMPUTED (the arithmetic is in the comments), not a copy of the code."""
import unittest

from fdb import matchup_card as mc
from fdb import matchup_pick as mp
from tests.test_matchup_card import AFTER_KICKOFF, BEFORE_KICKOFF, L, MartEnv


def g(home, away, hw, hl, aw, al, hs, as_, hx, ax):
    return {"home_id": home, "away_id": away, "home_w": hw, "home_l": hl, "away_w": aw, "away_l": al,
            "home_strength": hs, "away_strength": as_, "home_x": hx, "away_x": ax}


class Formula(unittest.TestCase):
    def test_hand_computed_scores(self):
        # Game 1: A (strength 300, starters 200, 3-0) v B (250, 190, 2-1).  Game 2: C (100, 120, 0-3) v D (150, 140, 1-2).
        # strengths: min 100, range 200 -> rank A 1.00, B 0.75, C 0.00, D 0.25.   K = 6, 3 games each -> weight 3/9 = 1/3.
        # no pedigree -> prior = strength rank.  quality = 1/3 * (wins/3) + 2/3 * prior:
        #   A = 1/3*1 + 2/3*1 = 1.0   B = 1/3*(2/3) + 2/3*0.75 = 0.72222   C = 0   D = 1/3*(1/3) + 2/3*0.25 = 0.27778
        # combined: game 1 = 390, game 2 = 260 -> size = (390-260)/130 = 1 and 0.
        # game 1: closeness = 1 - 10/390*6 = 0.846154; both_good (0.72222 > 0.5) = 0.10
        #   score = 0.72222*0.45 + 0.846154*0.25 + 1*0.10 + 0.10 - 0.40*(1-0.72222) = 0.625427
        # game 2: closeness = 1 - 20/260*6 = 0.538462; both_good 0
        #   score = 0*0.45 + 0.538462*0.25 + 0 + 0 - 0.40*0.27778 = 0.023504
        games = [g("C", "D", 0, 3, 1, 2, 100.0, 150.0, 120.0, 140.0), g("A", "B", 3, 0, 2, 1, 300.0, 250.0, 200.0, 190.0)]
        out = mp.rank_games(games, {}, "projection")
        self.assertEqual([(x["home_id"], x["rank"]) for x in out], [("A", 1), ("C", 2)])
        self.assertAlmostEqual(out[0]["score"], 0.625427, places=5)
        self.assertAlmostEqual(out[1]["score"], 0.023504, places=5)
        self.assertAlmostEqual(out[0]["quality_away"], 0.722222, places=5)
        self.assertAlmostEqual(out[0]["closeness"], 0.846154, places=5)

    def test_a_lopsided_game_of_good_teams_loses_to_a_close_one(self):
        close = g("A", "B", 3, 0, 3, 0, 300.0, 300.0, 200.0, 199.0)
        lopsided = g("C", "D", 3, 0, 3, 0, 300.0, 300.0, 250.0, 100.0)
        out = mp.rank_games([lopsided, close], {}, "projection")
        self.assertEqual(out[0]["home_id"], "A")

    def test_pedigree_lifts_a_team_with_a_thin_record(self):
        games = [g("A", "B", 1, 0, 1, 0, 100.0, 100.0, 100.0, 100.0), g("C", "D", 1, 0, 1, 0, 100.0, 100.0, 100.0, 100.0)]
        out = mp.rank_games(games, {"A": 1.0, "B": 1.0, "C": 0.0, "D": 0.0}, "projection")
        self.assertEqual(out[0]["home_id"], "A")

    def test_records_basis_drops_the_projection_terms(self):
        games = [g("A", "B", 3, 0, 2, 1, None, None, None, None), g("C", "D", 0, 3, 1, 2, None, None, None, None)]
        out = mp.rank_games(games, {}, "records")
        self.assertEqual(out[0]["home_id"], "A")
        self.assertIsNone(out[0]["closeness"])
        self.assertIsNone(out[0]["size"])

    def test_empty_and_ties_are_deterministic(self):
        self.assertEqual(mp.rank_games([], {}, "projection"), [])
        twin = [g("B", "C", 1, 1, 1, 1, 100.0, 100.0, 100.0, 100.0), g("A", "D", 1, 1, 1, 1, 100.0, 100.0, 100.0, 100.0)]
        self.assertEqual([x["home_id"] for x in mp.rank_games(twin, {}, "projection")], ["A", "B"])   # tie -> ids


class Pedigree(unittest.TestCase):
    def test_hand_computed(self):
        # Regular season: wk1 A 10-5 B, wk2 A 9-3 C, wk3 B 8-7 C.  Final (a playoff week with ONE game): B 6-5 A.
        # win% A 1.0, B 0.5, C 0.0;  points for (a week once) A 19, B 13, C 10 -> ranks 1, 0.3333, 0
        # reg = .5*wp + .5*pf: A 1.0, B 0.41667, C 0.0.  playoff bonus: champion B 1.0, finalist A 0.85
        # raw = 0.7*reg + 0.3*bonus: A 0.955, B 0.59167, C 0.0 -> normalised by the top: A 1.0, B 0.61952, C 0.0
        prior = [{"home_id": "A", "away_id": "B", "week": 1, "home_score": 10.0, "away_score": 5.0, "is_playoff": 0},
                 {"home_id": "A", "away_id": "C", "week": 2, "home_score": 9.0, "away_score": 3.0, "is_playoff": 0},
                 {"home_id": "B", "away_id": "C", "week": 3, "home_score": 8.0, "away_score": 7.0, "is_playoff": 0},
                 {"home_id": "B", "away_id": "A", "week": 15, "home_score": 6.0, "away_score": 5.0, "is_playoff": 1}]
        ped = mp.pedigree(prior)
        self.assertAlmostEqual(ped["A"], 1.0, places=5)
        self.assertAlmostEqual(ped["B"], 0.61952, places=4)
        self.assertAlmostEqual(ped["C"], 0.0, places=5)

    def test_no_prior_season_means_no_pedigree(self):
        self.assertEqual(mp.pedigree([]), {})
        self.assertEqual(mp.pedigree([{"home_id": "A", "away_id": "B", "week": 15, "home_score": 1.0, "away_score": 0.0, "is_playoff": 1}]), {})

    def test_a_week_with_two_games_is_not_a_final(self):
        prior = [{"home_id": "A", "away_id": "B", "week": 1, "home_score": 10.0, "away_score": 5.0, "is_playoff": 0},
                 {"home_id": "A", "away_id": "B", "week": 15, "home_score": 6.0, "away_score": 5.0, "is_playoff": 1},
                 {"home_id": "C", "away_id": "D", "week": 15, "home_score": 6.0, "away_score": 5.0, "is_playoff": 1}]
        self.assertEqual(set(mp.pedigree(prior)), {"A", "B"})   # no champion bonus: still computed from the regular season


class FromTheMart(unittest.TestCase):
    def test_mart_carries_the_selector_inputs(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            w1 = env.card(1, "0001", "0002")
            self.assertEqual(w1["is_playoff"], 0)
            self.assertEqual((w1["home_roster_actual"], w1["away_roster_actual"]), (103.0, 93.0))   # starter + a 3.0 bench player
            self.assertIsNone(w1["home_strength"])                                                  # no projection for a completed week
            w3 = env.card(3, "0001", "0002")
            self.assertEqual((w3["home_strength"], w3["away_strength"]), (20.0, 15.0))              # whole lineup, bench unprojected = 0
            self.assertIsNone(w3["home_roster_actual"])                                              # not played

    def test_a_bracket_week_is_flagged(self):
        with MartEnv() as env:
            env.seed_all()
            env.c.execute("UPDATE core_mfl_league SET lastRegularSeasonWeek = 1")
            env.c.commit()
            env.build()
            self.assertEqual(env.card(1, "0001", "0002")["is_playoff"], 0)
            self.assertEqual(env.card(2, "0001", "0002")["is_playoff"], 1)
            # records stay regular-season: week 3 counts week 1 only (0001 won both week-1 games)
            self.assertEqual((env.card(3, "0001", "0002")["home_w"], env.card(3, "0001", "0002")["home_l"]), (2, 0))

    def test_basis_follows_what_exists(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            self.assertEqual(mp.pick(env.c, L, 2026, 3)["basis"], "projection")
            self.assertEqual(mp.pick(env.c, L, 2026, 2)["basis"], "actual")        # completed, no pre-kickoff projection
        with MartEnv() as env:
            env.seed_all(preview_projection=False)
            env.build(now=AFTER_KICKOFF)
            p = mp.pick(env.c, L, 2026, 3)
            self.assertEqual(p["basis"], "records")                                # under way, nothing to compare
            self.assertIsNone(p["featured"]["closeness"])

    def test_exactly_one_game_is_featured_and_ranks_are_unique(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            for week in (1, 2, 3):
                gs = mc.games(env.c, L, 2026, week)
                self.assertEqual(len(gs), 4)
                self.assertEqual(sum(x["featured"] for x in gs), 1, week)
                self.assertEqual([x["rank"] for x in gs], [1, 2, 3, 4])
                self.assertTrue(gs[0]["featured"])

    def test_the_pick_is_deterministic(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            a = [(x["home_id"], x["away_id"], x["score"]) for x in mp.pick(env.c, L, 2026, 3)["ranked"]]
            env.build(now=BEFORE_KICKOFF)
            b = [(x["home_id"], x["away_id"], x["score"]) for x in mp.pick(env.c, L, 2026, 3)["ranked"]]
            self.assertEqual(a, b)

    def test_an_empty_week_has_no_pick(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            p = mp.pick(env.c, L, 2026, 17)
            self.assertEqual((p["featured"], p["ranked"], p["basis"]), (None, [], None))

    def test_card_says_it_is_featured_and_why(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            top = mc.games(env.c, L, 2026, 3)[0]
            c = mc.card(env.c, L, 2026, 3, top["home_id"], top["away_id"])
            self.assertTrue(c["featured"])
            self.assertEqual(c["pick"]["rank"], 1)
            self.assertTrue(any("pre-kickoff projections" in w for w in c["pick"]["why"]), c["pick"]["why"])
            self.assertIn("Matchup of the week", mc.card_html(c))
            other = mc.games(env.c, L, 2026, 3)[1]
            c2 = mc.card(env.c, L, 2026, 3, other["home_id"], other["away_id"])
            self.assertFalse(c2["featured"])
            self.assertNotIn("Matchup of the week", mc.card_html(c2))


if __name__ == "__main__":
    unittest.main()
