"""Phase 11: the Wednesday choice (`fdb choices`, fdb/matchup_choices.py), the `fdb post --game` override, and a recap's
"current record" (the mart's *_cur_* columns: through the card's own week for a FINAL card)."""
import unittest

from fdb import matchup_card as mc, matchup_choices as ch
from tests.test_discord_post import Post
from tests.test_matchup_card import BEFORE_KICKOFF, L, MartEnv


class Choices(unittest.TestCase):
    def test_the_top_games_come_with_pros_and_cons_in_picker_order(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            cands = ch.candidates(env.c, L, 2026, 3, n=2)
            self.assertEqual([c["rank"] for c in cands], [1, 2])
            self.assertGreaterEqual(cands[0]["score"], cands[1]["score"])
            for c in cands:
                self.assertTrue(c["pros"] or c["cons"])
                self.assertIn(" at ", c["records"])
            self.assertTrue(any("picker's top game" in x for x in cands[0]["pros"]))
            self.assertTrue(any(x.startswith("The picker ranks it 2 of") for x in cands[1]["cons"]))

    def test_a_named_game_is_added_even_when_it_is_outside_the_top_n(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            games = mc.games(env.c, L, 2026, 3)
            last = games[-1]
            cands = ch.candidates(env.c, L, 2026, 3, n=1, include=[(last["away_id"], last["home_id"])])    # either id order
            self.assertEqual(len(cands), 2)
            self.assertEqual({cands[-1]["home_id"], cands[-1]["away_id"]}, {last["home_id"], last["away_id"]})
            self.assertEqual(cands[-1]["rank"], last["rank"])

    def test_the_markdown_names_the_command_for_each_game(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            cands = ch.candidates(env.c, L, 2026, 3, n=2)
            text = ch.to_markdown({"league_name": "T", "season": 2026, "week": 3}, cands)
            for c in cands:
                self.assertIn(f"--game {c['home_id']}:{c['away_id']}", text)
            self.assertIn("How the picker scores a game", text)
            self.assertIn("Pro: ", text)

    def test_parse_pair(self):
        self.assertEqual(ch.parse_pair("0024:0023"), ("0024", "0023"))
        for bad in ("0024", "0024:", ":0023", "0024:0024", "a:b:c", ""):
            self.assertIsNone(ch.parse_pair(bad), bad)


class GameOverride(unittest.TestCase):
    def games(self, env):
        env.build(now=BEFORE_KICKOFF)
        return mc.games(env.c, L, 2026, 3)

    def test_a_chosen_game_is_the_one_posted_and_says_so(self):
        with Post() as env:
            games = self.games(env)
            other = games[1]
            rc, out = env.post("preview", now=BEFORE_KICKOFF, game=f"{other['away_id']}:{other['home_id']}")
            self.assertEqual(rc, 0, out)
            self.assertIn("game chosen by hand", out)
            self.assertIn(other["home_name"] if other["home_name"] in out else other["away_name"], out)
            self.assertNotIn("Why this game", out)                       # the picker's reasoning is not part of a hand pick

    def test_without_it_the_pickers_top_game_is_posted(self):
        with Post() as env:
            games = self.games(env)
            rc, out = env.post("preview", now=BEFORE_KICKOFF)
            self.assertEqual(rc, 0, out)
            self.assertNotIn("chosen by hand", out)
            self.assertIn(games[0]["home_name"] if games[0]["home_name"] in out else games[0]["away_name"], out)

    def test_a_game_that_is_not_in_the_week_is_refused_and_nothing_is_sent(self):
        with Post() as env:
            self.games(env)
            for bad in ("9999:8888", "0001", "0001:0001"):
                rc, out = env.post("preview", now=BEFORE_KICKOFF, game=bad, send_it=True, yes=True)
                self.assertEqual(rc, 1, (bad, out))
                self.assertIn("is not a game in week", out)
            self.assertEqual(env.fake.requests, [])
            self.assertEqual(env.rows(), [])


class CurrentRecord(unittest.TestCase):
    def test_a_final_card_counts_its_own_week_a_preview_does_not(self):
        """0001 won both week-1 games (100 v 90, 100 v 70) with a best lineup of 105 each."""
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            w1 = env.card(1, "0001", "0002")
            self.assertEqual((w1["state"], w1["home_w"], w1["home_pf"]), ("FINAL", 0, 0.0))                   # before the week
            self.assertEqual((w1["home_cur_w"], w1["home_cur_l"], w1["home_cur_pf"], w1["home_cur_opt_pf"]), (2, 0, 200.0, 210.0))
            p = env.c.execute("SELECT * FROM mart_matchup_card WHERE state = 'PREVIEW' LIMIT 1").fetchone()
            self.assertEqual((p["home_w"], p["home_l"], p["home_t"], p["home_pf"]),
                             (p["home_cur_w"], p["home_cur_l"], p["home_cur_t"], p["home_cur_pf"]))

    def test_the_card_reader_shows_the_current_record_for_a_final_game(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            c = mc.card(env.c, L, 2026, 1, "0001", "0002")
            self.assertEqual((c["home"]["w"], c["home"]["l"], c["home"]["pf"], c["home"]["opt_pf"]), (2, 0, 200.0, 210.0))
            self.assertIn("after this week", mc.card_html(c))
            pre = mc.card(env.c, L, 2026, 3, *[mc.games(env.c, L, 2026, 3)[0][k] for k in ("home_id", "away_id")])
            self.assertEqual(pre["state"], "PREVIEW")
            self.assertIn("before this week", mc.card_html(pre))


if __name__ == "__main__":
    unittest.main()
