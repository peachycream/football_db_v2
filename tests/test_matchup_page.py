"""Phase 11: the card data layer (fdb/matchup_card.py) and the /matchup/ review page (app/matchup_card.py).
Built on the same fixtures as tests/test_matchup_card.py; the page reads mart_matchup_card* only and writes nothing."""
import unittest

from fdb import matchup_card as mc
from tests.test_matchup_card import AFTER_KICKOFF, BEFORE_KICKOFF, L, MartEnv


def client():
    from app import create_app
    app = create_app()
    app.logger.setLevel("CRITICAL")
    return app.test_client()


class Colors(unittest.TestCase):
    def test_distinct_colors_are_kept(self):
        self.assertEqual(mc.pick_colors("#FFB612", "#E8E8E8", "#FB4F14", "#E8E8E8"), ("#FFB612", "#FB4F14"))

    def test_two_oranges_take_the_alternate(self):
        h, a = mc.pick_colors("#FB4F14", "#E8E8E8", "#FF7A1A", "#5B7FBF")   # Bengals v Broncos
        self.assertEqual((h, a), ("#FB4F14", "#5B7FBF"))

    def test_missing_or_invalid_colors_fall_back_and_always_differ(self):
        for args in ((None, None, None, None), ("red", None, "#12", None), ("#FB4F14", None, "#FB4F14", None)):
            h, a = mc.pick_colors(*args)
            self.assertGreaterEqual(mc._distance(h, a), mc.MIN_COLOR_DISTANCE, args)

    def test_tint_is_a_dark_mix_of_the_color(self):
        t = mc.tint("#FFB612", 0.3)
        self.assertRegex(t, r"^#[0-9A-F]{6}$")
        self.assertLess(sum(mc._rgb(t)), sum(mc._rgb("#FFB612")))


class Probability(unittest.TestCase):
    def test_even_projections_are_a_coin_flip_and_the_two_sides_add_to_one(self):
        p = mc.win_probability(100.0, 100.0)
        self.assertAlmostEqual(p["home"], 0.5)
        q = mc.win_probability(120.0, 100.0)
        self.assertGreater(q["home"], 0.5)
        self.assertAlmostEqual(q["home"] + q["away"], 1.0)

    def test_no_projection_means_no_probability(self):
        self.assertIsNone(mc.win_probability(None, 100.0))
        self.assertIsNone(mc.win_probability(100.0, None))


class CardData(unittest.TestCase):
    def test_final_card_uses_actuals_and_never_projections(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            c = mc.card(env.c, L, 2026, 1, "0001", "0002")
            self.assertEqual((c["state"], c["winner"], c["margin"], c["board_basis"], c["players_basis"]),
                             ("FINAL", "home", 10.0, "actual", "actual"))
            self.assertIsNone(c["win_prob"])   # the game is over
            self.assertEqual(c["players"]["home"][0]["value"], 100.0)
            self.assertTrue(any("won by 10.00" in t for _, t in c["takeaways"]), c["takeaways"])

    def test_preview_card_is_projected_with_a_probability_and_no_result(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            c = mc.card(env.c, L, 2026, 3, "0001", "0002")
            self.assertEqual((c["state"], c["winner"], c["margin"], c["board_basis"]), ("PREVIEW", None, None, "projected"))
            self.assertEqual((c["home"]["proj"], c["away"]["proj"]), (20.0, 15.0))
            self.assertAlmostEqual(c["win_prob"]["home"] + c["win_prob"]["away"], 1.0)
            self.assertGreater(c["win_prob"]["home"], 0.5)
            self.assertEqual(c["players_basis"], "projected")
            self.assertTrue(any("Projected gap is 5.0" in t for _, t in c["takeaways"]), c["takeaways"])
            # 0001 starts a QB (proj 20), 0002 a LB (proj 15): each group's edge is home minus away
            self.assertEqual({b["grp"]: b["edge"] for b in c["board"]}, {"QB": 20.0, "LB": -15.0})
            self.assertEqual(c["biggest"], "QB")

    def test_without_a_pre_kickoff_projection_nothing_projected_is_shown(self):
        with MartEnv() as env:
            env.seed_all(preview_projection=False)
            env.build(now=AFTER_KICKOFF)
            c = mc.card(env.c, L, 2026, 3, "0001", "0002")
            self.assertEqual((c["win_prob"], c["board"], c["players_basis"], c["home"]["proj"]), (None, [], None, None))
            self.assertTrue(any("No projection was captured before kickoff" in n for n in c["notes"]), c["notes"])

    def test_unknown_game_is_none(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            self.assertIsNone(mc.card(env.c, L, 2026, 1, "0001", "0003"))

    def test_games_list_orders_by_the_weaker_teams_record(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            gs = mc.games(env.c, L, 2026, 2)
            self.assertEqual(len(gs), 4)
            # before week 2: 0001 2-0, 0002 1-1, 0003 1-1, 0004 0-2. Weaker-team record: 0001 v 0002 .500, 0002 v 0003 .500,
            # 0003 v 0004 0, 0004 v 0001 0. The .500 tie goes to the larger combined points for (190 v 170).
            self.assertEqual([{g["home_id"], g["away_id"]} for g in gs[:2]], [{"0001", "0002"}, {"0002", "0003"}])
            self.assertEqual({g["home_id"] for g in gs[2:]} | {g["away_id"] for g in gs[2:]}, {"0003", "0004", "0001"})
            self.assertEqual(mc.rec(2, 1, 1), "2-1-1")

    def test_week_state_is_final_only_when_every_game_is(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            self.assertEqual(mc._week_state(env.c, L, 2026, 2), "FINAL")
            self.assertEqual(mc._week_state(env.c, L, 2026, 3), "LIVE")
            self.assertEqual([w["week"] for w in mc.weeks(env.c, L, 2026)], [3, 2, 1])


class Html(unittest.TestCase):
    def render(self, mutate=None, week=1, home="0001", away="0002", now=AFTER_KICKOFF):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=now)
            if mutate:
                mutate(env.c)
                env.c.commit()
            return mc.card_html(mc.card(env.c, L, 2026, week, home, away))

    def test_final_card_shows_the_winner_and_both_scores(self):
        h = self.render()
        for needle in ("Winner", "Final", "100.00", "90.00", "Won by 10.00", "Lost by 10.00", "Left on the bench"):
            self.assertIn(needle, h)
        self.assertNotIn("Projection edge", h)

    def test_database_text_is_escaped(self):
        h = self.render(lambda c: c.execute("UPDATE mart_matchup_card SET home_name = '<img src=x onerror=alert(1)>' WHERE week = 1 AND home_id = '0001'"))
        self.assertNotIn("<img src=x", h)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", h)

    def test_only_http_logos_are_used(self):
        h = self.render(lambda c: c.execute("UPDATE mart_matchup_card SET home_logo = 'javascript:alert(1)', away_logo = 'https://img.example/x.png' "
                                            "WHERE week = 1 AND home_id = '0001'"))
        self.assertNotIn("javascript:", h)
        self.assertIn('src="https://img.example/x.png"', h)

    def test_preview_has_no_winner_tag_and_shows_the_edge_bar(self):
        h = self.render(week=3, now=BEFORE_KICKOFF)
        self.assertNotIn("Winner", h)
        self.assertIn("Projection edge", h)
        self.assertIn("Preview", h)

    def test_a_logo_failure_falls_back_to_the_abbreviation_ring(self):
        h = self.render()   # no logos in the fixtures
        self.assertIn("border:22px solid", h)


class Page(unittest.TestCase):
    def test_empty_database_says_what_to_run(self):
        with MartEnv() as env:
            env.c.commit()
            r = client().get("/matchup/")
            self.assertEqual(r.status_code, 200)
            self.assertIn("No matchup data yet", r.data.decode())

    def test_page_defaults_to_the_newest_week_and_lists_its_games(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            r = client().get("/matchup/")
            body = r.data.decode()
            self.assertEqual(r.status_code, 200)
            self.assertIn("Review only", body)
            self.assertIn("4 GAMES", body)
            self.assertIn("In progress", body)             # week 3 is under way

    def test_page_for_a_chosen_final_game_and_its_card_only_view(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            c = client()
            body = c.get(f"/matchup/?league={L}&season=2026&week=1&home=0001&away=0002").data.decode()
            self.assertIn("Winner", body)
            self.assertIn("card only", body)
            only = c.get(f"/matchup/card/?league={L}&season=2026&week=1&home=0001&away=0002")
            self.assertEqual(only.status_code, 200)
            self.assertNotIn("Review only", only.data.decode())
            self.assertIn("Won by 10.00", only.data.decode())
            self.assertEqual(c.get("/matchup/card/?home=x&away=y").status_code, 404)

    def test_bad_query_values_fall_back_instead_of_failing(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            env.c.commit()
            c = client()
            for q in ("?league=nope", "?season=abc", "?week=99", "?week=x&home=%3Cb%3E&away=1"):
                self.assertEqual(c.get("/matchup/" + q).status_code, 200, q)

    def test_json_endpoints(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            c = client()
            g = c.get(f"/api/matchup/games?league={L}&season=2026&week=1").get_json()
            self.assertEqual(len(g["games"]), 4)
            d = c.get(f"/api/matchup/card?league={L}&season=2026&week=1&home=0001&away=0002").get_json()
            self.assertEqual((d["state"], d["winner"], d["home"]["score"]), ("FINAL", "home", 100.0))
            self.assertEqual(c.get("/api/matchup/card?home=x&away=y").status_code, 404)

    def test_the_page_never_writes(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            before = env.c.execute("SELECT COUNT(*) FROM mart_matchup_card").fetchone()[0], env.c.execute("SELECT COUNT(*) FROM load_log").fetchone()[0]
            c = client()
            c.get("/matchup/")
            c.get(f"/matchup/card/?league={L}&season=2026&week=1&home=0001&away=0002")
            self.assertEqual(before, (env.c.execute("SELECT COUNT(*) FROM mart_matchup_card").fetchone()[0],
                                      env.c.execute("SELECT COUNT(*) FROM load_log").fetchone()[0]))

    def test_nav_and_hub_link_to_the_page(self):
        from app import shell
        self.assertIn(("/matchup/", "MATCHUP CARD"), shell.NAV_LINKS)
        self.assertTrue(any(h == "/matchup/" for h, _, _ in shell.HUB_APPS))
        self.assertIn("/matchup/", client().get("/").data.decode())


if __name__ == "__main__":
    unittest.main()
