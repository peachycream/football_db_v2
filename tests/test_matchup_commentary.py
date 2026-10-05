"""Phase 11: the written breakdown (fdb/matchup_commentary.py), the best-bench-scorer mart columns it uses, and the landscape
panels a Discord post carries (fdb/matchup_card.panel_html, card_render.render_panels).

Fixture (tests/test_matchup_card.py): league 11111, franchises A B C D in a ring, each playing TWO games a week. Week 1 scores
A 100, B 90, C 80, D 70; week 2 A 60, B 70, C 80, D 90. Each starts one player `<id>1` (A a QB, B a LB, C a safety, D a WR) and
has one bench player `<id>2` who scored 3.0 and is not in the identity tables (so shows by MFL id)."""
import unittest

from fdb import card_render as cr
from fdb import matchup_card as mc
from fdb import matchup_commentary as cm
from tests.test_matchup_card import AFTER_KICKOFF, BEFORE_KICKOFF, L, MartEnv


def lead_text(paras):
    return {p["lead"]: p["text"] for p in paras}


class Helpers(unittest.TestCase):
    def test_ordinals(self):
        got = [cm.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112)]
        self.assertEqual(got, ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "112th"])

    def test_possessives_of_team_names(self):
        self.assertEqual(cm.poss("Cincinnati Bengals"), "Cincinnati Bengals'")
        self.assertEqual(cm.poss("Chicago Bear"), "Chicago Bear's")

    def test_to_markdown_trims_the_last_paragraphs_first_and_never_exceeds_the_limit(self):
        paras = [{"lead": f"P{i}", "text": "word " * 60} for i in range(6)]
        text = cm.to_markdown(paras, limit=700)
        self.assertLessEqual(len(text), 700)
        self.assertTrue(text.startswith("**P0.**"))
        self.assertIn("**P1.**", text)
        self.assertNotIn("**P5.**", text)

    def test_one_overlong_paragraph_ends_at_a_sentence(self):
        text = cm.to_markdown([{"lead": "Only", "text": "First sentence here. " * 80}], limit=300)
        self.assertLessEqual(len(text), 300)
        self.assertTrue(text.endswith("."))

    def test_nothing_to_say_is_an_empty_string(self):
        self.assertEqual(cm.to_markdown([]), "")


class Recap(unittest.TestCase):
    def card(self, env, week=1, home="0001", away="0002", now=AFTER_KICKOFF):
        env.seed_all()
        env.build(now=now)
        return mc.card(env.c, L, 2026, week, home, away)

    def test_the_result_names_the_winner_the_margin_and_where_the_scores_ranked(self):
        with MartEnv() as env:
            t = lead_text(cm.recap_paragraphs(env.c, self.card(env)))["The result"]
            self.assertIn("A beat B 100.00 to 90.00, a margin of 10.00.", t)
            self.assertIn("2nd-largest margin of the week's 4 games", t)       # margins 30, 10, 10, 10: one is larger
            self.assertIn("the best in the league of 4 teams", t)              # A's 100 tops 100, 90, 80, 70
            self.assertIn("B' ranked 2nd", t.replace("B's", "B'"))             # B's 90 is second

    def test_how_it_was_won_uses_the_position_board(self):
        with MartEnv() as env:
            t = lead_text(cm.recap_paragraphs(env.c, self.card(env)))["How it was won"]
            self.assertIn("A won 1 of 2 position groups, led by QB (+100.0).", t)
            self.assertIn("B led LB by 90.0.", t)

    def test_the_stars_come_from_the_lineups(self):
        with MartEnv() as env:
            t = lead_text(cm.recap_paragraphs(env.c, self.card(env)))["The stars"]
            self.assertIn("Player 0001 (QB) led A with 100.0, 100.0% of the team's total", t)
            self.assertIn("Player 0002 (MLB) led B with 90.0", t)
            self.assertIn("best single score of the game was Player 0001's 100.0", t)

    def test_the_bench_counts_points_left_names_the_best_sitters_and_does_the_what_if(self):
        with MartEnv() as env:
            t = lead_text(cm.recap_paragraphs(env.c, self.card(env)))["The bench"]
            self.assertIn("B left 5.0 points on the bench (best possible lineup 95.0, 94.7% captured)", t)
            self.assertIn("A left 5.0 (105.0, 95.2%)", t)
            self.assertIn("MFL 00022", t)                                       # an unresolved id is shown by its MFL id, never guessed
            self.assertIn("(3.0)", t)
            self.assertIn("Even a perfect lineup (95.0) would not have changed the result.", t)

    def test_a_loser_whose_perfect_lineup_would_have_won_is_told_so(self):
        with MartEnv() as env:
            c = self.card(env)
            c["away"]["opt"] = 140.0      # B's best possible lineup beats A's 100
            t = lead_text(cm.recap_paragraphs(env.c, c))["The bench"]
            self.assertIn("With a perfect lineup B would have won (140.0 to 100.00).", t)

    def test_the_series_after_the_game_and_the_previous_meeting(self):
        with MartEnv() as env:
            first = lead_text(cm.recap_paragraphs(env.c, self.card(env)))["The series"]
            self.assertIn("first regular-season meeting between A and B, and A won it", first)
        with MartEnv() as env:
            t = lead_text(cm.recap_paragraphs(env.c, self.card(env, week=2)))["The series"]
            # week 1: A beat B; week 2: B beats A -> level at 1-1 across 2 meetings
            self.assertIn("B level the all-time series at 1-1 across 2 regular-season meetings.", t)
            self.assertIn("The previous meeting was 2026 week 1: 0001 100.00, 0002 90.00.", t)

    def test_what_is_next_names_next_weeks_opponents_when_they_are_known(self):
        with MartEnv() as env:
            t = lead_text(cm.recap_paragraphs(env.c, self.card(env, week=2)))["Next"]
            self.assertIn("In week 3, ", t)
            self.assertIn("A play ", t)

    def test_no_next_paragraph_when_the_next_week_is_not_in_the_data(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.execute("DELETE FROM mart_matchup_card WHERE week = 3")
            c = mc.card(env.c, L, 2026, 2, "0001", "0002")
            self.assertNotIn("Next", lead_text(cm.recap_paragraphs(env.c, c)))

    def test_a_playoff_game_does_not_claim_a_series_result(self):
        with MartEnv() as env:
            c = self.card(env)
            c["is_playoff"] = True
            self.assertNotIn("The series", lead_text(cm.recap_paragraphs(env.c, c)))

    def test_a_tie_is_reported_as_a_tie(self):
        with MartEnv() as env:
            c = self.card(env)
            c["home"]["score"] = c["away"]["score"] = 95.0
            c["winner"], c["margin"] = "tie", 0.0
            self.assertIn("tied at 95.00", lead_text(cm.recap_paragraphs(env.c, c))["The result"])

    def test_every_paragraph_is_made_of_its_numbers_nothing_is_emitted_without_them(self):
        with MartEnv() as env:
            c = self.card(env)
            c["board"], c["players_basis"], c["bench"] = [], None, {}
            c["home"]["opt"] = c["away"]["opt"] = None
            self.assertEqual(set(lead_text(cm.recap_paragraphs(env.c, c))), {"The result", "The series", "Next"})

    def test_a_game_that_is_not_final_has_no_recap(self):
        with MartEnv() as env:
            c = self.card(env, week=3, now=BEFORE_KICKOFF)
            self.assertEqual(cm.recap_paragraphs(env.c, c), [])
            self.assertEqual(cm.paragraphs(env.c, c), cm.preview_paragraphs(env.c, c))

    def test_the_whole_recap_fits_a_discord_message(self):
        with MartEnv() as env:
            md = cm.to_markdown(cm.paragraphs(env.c, self.card(env)), limit=1970)
            self.assertLessEqual(len(md), 1970)
            self.assertIn("**The result.**", md)

    def test_the_same_data_gives_the_same_words(self):
        with MartEnv() as env:
            c = self.card(env)
            self.assertEqual(cm.paragraphs(env.c, c), cm.paragraphs(env.c, c))


class Preview(unittest.TestCase):
    def test_the_preview_says_who_is_projected_ahead_where_and_who_to_watch(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            c = mc.card(env.c, L, 2026, 3, "0001", "0002")
            t = lead_text(cm.preview_paragraphs(env.c, c))
            self.assertIn("B (0-", t["The matchup"] + "B (0-")                  # records are shown
            self.assertIn("The projections have A ahead by 5.0 points (20.0 to 15.0)", t["The matchup"])
            self.assertIn("It is a division game.", t["The matchup"])
            self.assertIn("A lead QB (+20.0)", t["Position battles"])
            self.assertIn("B lead LB (+15.0)", t["Position battles"])
            self.assertIn("Players to watch", t)
            self.assertIn("The series", t)

    def test_a_preview_explains_why_it_is_the_featured_game_and_where_both_teams_stand(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            top = mc.games(env.c, L, 2026, 3)[0]
            c = mc.card(env.c, L, 2026, 3, top["home_id"], top["away_id"])
            t = lead_text(cm.preview_paragraphs(env.c, c))
            self.assertIn("It ranks first of 4 games on the picker's score.", t["Why this game"])
            self.assertIn("projected totals are only", t["Why this game"])
            self.assertIn("by record", t["The stakes"])
            self.assertIn("points for", t["The stakes"])
            self.assertIn("The biggest gap is", t["Position battles"])
            second = mc.games(env.c, L, 2026, 3)[1]
            c2 = mc.card(env.c, L, 2026, 3, second["home_id"], second["away_id"])
            self.assertNotIn("Why this game", lead_text(cm.preview_paragraphs(env.c, c2)))   # only the featured game is explained

    def test_rank_text_names_ties(self):
        self.assertEqual(cm._rank_text(5.0, [9.0, 5.0, 5.0, 1.0]), "tied for 2nd")
        self.assertEqual(cm._rank_text(9.0, [9.0, 5.0, 5.0, 1.0]), "1st")
        self.assertEqual(cm._rank_text(1.0, [9.0, 5.0, 5.0, 1.0]), "4th")

    def test_nobody_has_played_means_no_stakes_paragraph(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            c = mc.card(env.c, L, 2026, 3, "0001", "0002")
            env.c.execute("UPDATE mart_matchup_card SET home_w = 0, home_l = 0, home_t = 0, away_w = 0, away_l = 0, away_t = 0 WHERE week = 3")
            self.assertNotIn("The stakes", lead_text(cm.preview_paragraphs(env.c, c)))

    def test_a_preview_without_a_projection_says_nothing_projected(self):
        with MartEnv() as env:
            env.seed_all(preview_projection=False, post_projection=False)
            env.build(now=BEFORE_KICKOFF)
            c = mc.card(env.c, L, 2026, 3, "0001", "0002")
            t = lead_text(cm.preview_paragraphs(env.c, c))
            self.assertEqual(set(t), {"The matchup", "Why this game", "The stakes", "The series"})
            self.assertNotIn("projections have", t["The matchup"])
            self.assertNotIn("projected totals", t["Why this game"])            # no closeness without projections
            self.assertNotIn("Position battles", t)
            self.assertNotIn("Players to watch", t)


class BenchColumns(unittest.TestCase):
    def test_the_mart_carries_the_best_scorer_left_on_each_bench(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            r = env.card(1, "0001", "0002")
            self.assertEqual((r["home_bench_best_name"], r["home_bench_best_score"]), ("MFL 00012", 3.0))
            self.assertEqual((r["away_bench_best_name"], r["away_bench_best_score"]), ("MFL 00022", 3.0))

    def test_only_completed_games_have_a_bench(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            r = env.card(3, "0001", "0002")
            self.assertEqual((r["home_bench_best_name"], r["home_bench_best_score"]), (None, None))


class Panels(unittest.TestCase):
    def cards(self, env):
        env.seed_all()
        env.build(now=BEFORE_KICKOFF)
        return (mc.card(env.c, L, 2026, 2, "0001", "0002"), mc.card(env.c, L, 2026, 3, "0001", "0002"))

    def test_cover_has_the_teams_and_the_tape_but_not_the_board(self):
        with MartEnv() as env:
            final, _ = self.cards(env)
            h = mc.panel_html(final, "cover")
            self.assertIn('class="mc panel"', h)
            self.assertIn("Winner", h)
            self.assertIn("Tale of the tape", h)
            self.assertNotIn("Position edge", h)

    def test_board_has_a_legend_naming_the_sides_and_the_bench_strip_when_final(self):
        with MartEnv() as env:
            final, _ = self.cards(env)
            h = mc.panel_html(final, "board")
            self.assertIn("Position edge", h)
            self.assertIn("&#9664; B", h)                                         # left = away
            self.assertIn("A &#9654;", h)                                         # right = home
            self.assertIn("Left on the bench", h)
            self.assertNotIn("Tale of the tape", h)

    def test_a_preview_board_shows_players_to_watch_instead_of_the_bench(self):
        with MartEnv() as env:
            _, pre = self.cards(env)
            h = mc.panel_html(pre, "board")
            self.assertIn("Players to watch", h)
            self.assertNotIn("Left on the bench", h)
            self.assertIn("projected points", h)
            self.assertIn("Projection edge", mc.panel_html(pre, "cover"))

    def test_a_week_with_no_projection_says_so_on_the_board_panel(self):
        with MartEnv() as env:
            env.seed_all(preview_projection=False, post_projection=False)
            env.build(now=BEFORE_KICKOFF)
            c = mc.card(env.c, L, 2026, 3, "0001", "0002")
            self.assertIn("No projection was captured before kickoff", mc.panel_html(c, "board"))

    def test_an_unknown_panel_is_refused(self):
        with MartEnv() as env:
            final, _ = self.cards(env)
            with self.assertRaises(ValueError):
                mc.panel_html(final, "nope")

    def test_the_whole_card_page_is_unchanged_in_structure(self):
        with MartEnv() as env:
            final, _ = self.cards(env)
            h = mc.card_html(final)
            for needle in ("Winner", "Position edge", "Tale of the tape", "Left on the bench", "Top performers"):
                self.assertIn(needle, h)
            self.assertNotIn("mc panel", h)


class PageRoutes(unittest.TestCase):
    def client(self):
        from tests.test_matchup_page import client
        return client()

    def test_the_review_page_shows_the_breakdown_and_links_to_both_images(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            body = self.client().get(f"/matchup/?league={L}&season=2026&week=1&home=0001&away=0002").data.decode()
            self.assertIn("THE BREAKDOWN (posted as the third message)", body)
            self.assertIn("<b>The result.</b>", body)
            self.assertIn("which=cover", body)
            self.assertIn("which=board", body)

    def test_a_breakdown_with_markup_in_a_name_is_escaped_on_the_page(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.execute("UPDATE mart_matchup_card SET home_name = '<script>alert(1)</script>' WHERE week = 1 AND home_id = '0001'")
            env.c.commit()
            body = self.client().get(f"/matchup/?league={L}&season=2026&week=1&home=0001&away=0002").data.decode()
            self.assertNotIn("<script>alert(1)", body)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)

    def test_panel_route_refuses_an_unknown_panel_and_an_unknown_game(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            c = self.client()
            self.assertEqual(c.get(f"/matchup/panel.png?which=nope&league={L}").status_code, 400)
            self.assertEqual(c.get(f"/matchup/panel.png?which=cover&league={L}&season=2026&week=1&home=x&away=y").status_code, 404)

    def test_panel_route_says_503_when_the_render_cannot_run(self):
        from unittest import mock
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            with mock.patch.object(cr, "render_panels", side_effect=cr.RenderError("no browser")):
                r = self.client().get(f"/matchup/panel.png?which=board&league={L}&season=2026&week=1&home=0001&away=0002")
            self.assertEqual(r.status_code, 503)
            self.assertIn("no browser", r.data.decode())


def _chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_chromium_available(), "Playwright's Chromium is not installed")
class RealRender(unittest.TestCase):
    def test_both_panels_render_landscape_and_larger_than_the_old_tall_card(self):
        import struct
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            c = mc.card(env.c, L, 2026, 1, "0001", "0002")
            panels = cr.render_panels(c, embed=False)
            self.assertEqual(list(panels), ["cover", "board"])
            for name, png in panels.items():
                self.assertTrue(png.startswith(bytes([0x89]) + b"PNG"), name)
                w, h = struct.unpack(">II", png[16:24])
                self.assertGreater(w / h, 1.15, f"{name} must be landscape: Discord shows a tall image tiny")
            tall = cr.render_png(c, embed=False)
            tw, th = struct.unpack(">II", tall[16:24])
            self.assertLess(tw / th, 1.0)                                          # the one-piece card is still the tall one


if __name__ == "__main__":
    unittest.main()
