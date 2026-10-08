"""Phase 11: the "so far" card. MFL liveScoring (mfl.live_scores / mfl.live_players) -> mart_matchup_card's live columns ->
the LIVE card, its commentary, and `fdb post --mode live`. Offline fixtures: the same four-franchise ring as the other matchup tests
(each plays TWO games a week, like 30590), week 3 next. The payload shape was recorded live on 2026-10-08 (30590 wk5, before kickoff)."""
import json
import os
import unittest
from unittest import mock

from fdb import loader as fw, matchup_card as mc, matchup_commentary as cm, matchup_weeks as mw
from fdb.loaders import get
from tests.test_discord_post import Post
from tests.test_fantasy import write_raw
from tests.test_matchup_card import AFTER_KICKOFF, BEFORE_KICKOFF, L, MartEnv

SCORES = {"0001": 50.0, "0002": 40.0, "0003": 30.0, "0004": 20.0}


def live_payload(week=3, scores=SCORES, yet=1, playing=0, status="starter", drift=0.0):
    """liveScoring as MFL answers it: matchup[].franchise[2], each franchise with its players. drift != 0 breaks the invariant that
    the starters add up to the franchise score."""
    def fr(fid, home):
        return {"id": fid, "isHome": home, "score": f"{scores[fid]:.2f}", "gameSecondsRemaining": str(yet * 3600),
                "playersYetToPlay": str(yet), "playersCurrentlyPlaying": str(playing),
                "players": {"player": [{"id": f"{fid}1", "status": status, "score": f"{scores[fid] + drift:.2f}",
                                        "gameSecondsRemaining": "3600", "updatedStats": ""}]}}
    ring = [("0001", "0002"), ("0002", "0003"), ("0003", "0004"), ("0004", "0001")]
    return {"version": "1.0", "liveScoring": {"week": str(week), "matchup": [{"franchise": [fr(a, "1"), fr(b, "0")]} for a, b in ring]}}


class LiveEnv(MartEnv):
    def live(self, payload=None, now=AFTER_KICKOFF):
        write_raw("mfl", "liveScoring", f"2026/{L}/REG03", payload or live_payload())
        out = []
        for lid in ("mfl.live_scores", "mfl.live_players"):
            out += self.load_all(lid)
        return out


class Loader(unittest.TestCase):
    def test_every_game_is_a_row_with_its_opponent_and_a_franchise_has_one_lineup(self):
        body = json.dumps(live_payload()).encode()
        fields, rows = get("mfl.live_scores").parse(body)
        self.assertEqual(len(rows), 8)
        self.assertEqual({(r["id"], r["opponent_id"]) for r in rows} & {("0001", "0002"), ("0001", "0004")},
                         {("0001", "0002"), ("0001", "0004")})
        self.assertNotIn("players", fields)
        pf, prows = get("mfl.live_players").parse(body)
        self.assertEqual(sorted(r["franchise_id"] for r in prows), ["0001", "0002", "0003", "0004"])   # not once per game

    def test_the_contracts_name_what_the_payload_carries(self):
        body = json.dumps(live_payload()).encode()
        for lid in ("mfl.live_scores", "mfl.live_players"):
            ld = get(lid)
            fields, _ = ld.parse(body)
            self.assertEqual(set(fields), set(ld.expected_fields()), lid)

    def test_a_franchise_with_different_lineups_in_its_two_games_is_refused(self):
        p = live_payload()
        p["liveScoring"]["matchup"][0]["franchise"][0]["players"]["player"][0]["score"] = "49.00"   # 0001 in its first game only
        with self.assertRaises(ValueError):
            get("mfl.live_players").parse(json.dumps(p).encode())

    def test_loading_stores_scores_and_players_and_they_agree(self):
        with LiveEnv() as env:
            env.seed_all()
            res = env.live()
            self.assertTrue(res and all(r["failures"] == [] for r in res), res)
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM core_mfl_live_scores").fetchone()[0], 8)
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM core_mfl_live_players").fetchone()[0], 4)
            self.assertEqual(env.c.execute("SELECT score FROM core_mfl_live_scores WHERE id = '0001' LIMIT 1").fetchone()[0], 50.0)

    def test_starters_that_do_not_add_to_the_score_fail_the_load(self):
        with LiveEnv() as env:
            env.seed_all()
            res = env.live(live_payload(drift=5.0))
            fails = [f for r in res for f in r["failures"]]
            self.assertTrue(any("do not add to the live score" in f for f in fails), fails)


class WhichWeek(unittest.TestCase):
    def bases(self, env, now):
        with mock.patch.dict(os.environ, {"FDB_NOW": now}):
            return [s.week for s in get("mfl.live_scores").snapshot_bases(env.c, 2026, L, True)]

    def test_only_a_week_that_has_kicked_off_and_is_not_complete_is_fetched(self):
        with LiveEnv() as env:
            env.seed_all()
            self.assertEqual(self.bases(env, BEFORE_KICKOFF), [])            # week 3 has not kicked off; weeks 1-2 are complete
            self.assertEqual(self.bases(env, AFTER_KICKOFF), [3])            # under way


class Mart(unittest.TestCase):
    def test_a_week_in_progress_carries_points_so_far_and_starters_still_to_play(self):
        with LiveEnv() as env:
            env.seed_all()
            env.live()
            env.build(now=AFTER_KICKOFF)
            g = env.card(3, "0001", "0002") or env.card(3, "0002", "0001")
            self.assertEqual(g["state"], "LIVE")
            self.assertIsNotNone(g["live_snapshot_at"])
            self.assertEqual((g["home_live_score"], g["away_live_score"], g["home_live_yet"], g["away_live_playing"]),
                             (SCORES[g["home_id"]], SCORES[g["away_id"]], 1, 0))
            # the starters' points so far are the players' and groups' "actual"
            act = env.c.execute("""SELECT source_player_id, actual FROM mart_matchup_card_players WHERE week = 3 AND franchise_id = ?""",
                                (g["home_id"],)).fetchall()
            self.assertEqual([(r[0], r[1]) for r in act], [(f"{g['home_id']}1", SCORES[g["home_id"]])])
            self.assertIsNone(g["home_score"])                                # a final score is not invented for a live game

    def test_without_a_live_snapshot_there_is_nothing_so_far(self):
        with LiveEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            g = env.c.execute("SELECT * FROM mart_matchup_card WHERE week = 3 LIMIT 1").fetchone()
            self.assertEqual(g["state"], "LIVE")
            self.assertIsNone(g["home_live_score"])
            t = mw.live_target(env.c, L)
            self.assertFalse(t["ready"])
            self.assertIn("live-refresh", t["reason"])

    def test_a_final_week_never_carries_live_numbers(self):
        with LiveEnv() as env:
            env.seed_all()
            env.live()
            env.build(now=AFTER_KICKOFF)
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM mart_matchup_card WHERE state = 'FINAL' AND home_live_score IS NOT NULL").fetchone()[0], 0)


class Card(unittest.TestCase):
    def card(self, env):
        env.seed_all()
        env.live()
        env.build(now=AFTER_KICKOFF)
        t = mw.live_target(env.c, L)
        self.assertTrue(t["ready"], t)
        f = t["featured"]
        return mc.card(env.c, L, 2026, 3, f["home_id"], f["away_id"])

    def test_the_card_says_so_far_and_makes_no_win_probability(self):
        with LiveEnv() as env:
            c = self.card(env)
            self.assertTrue(c["live"])
            self.assertIsNone(c["win_prob"])
            self.assertEqual(c["board_basis"], "so_far")
            self.assertEqual(c["players_basis"], "so_far")
            html = mc.card_html(c)
            self.assertIn("So far", html)
            self.assertIn("yet to play", html)
            self.assertIn("points so far", html)
            self.assertNotIn("Projection edge", html)

    def test_the_commentary_leads_with_who_is_ahead_and_how_many_starters_are_left(self):
        with LiveEnv() as env:
            c = self.card(env)
            paras = cm.paragraphs(env.c, c)
            lead = {p["lead"]: p["text"] for p in paras}
            self.assertIn("So far", lead)
            ahead = c["home"] if c["home"]["live"] > c["away"]["live"] else c["away"]
            self.assertIn(f"{ahead['name']} lead", lead["So far"])
            self.assertIn("yet to play", lead["So far"])
            self.assertIn("Top scorers so far", lead)
            self.assertTrue(set(lead) <= {"So far", "Position battles so far", "Top scorers so far", "The stakes", "The series"}, lead)


class LivePost(Post):
    live = LiveEnv.live


class PostLive(unittest.TestCase):
    def test_a_dry_run_renders_the_live_card_and_says_so(self):
        with LivePost() as env:
            env.live()
            rc, out = env.post("live", now=AFTER_KICKOFF)
            self.assertEqual(rc, 0, out)
            self.assertIn("so far", out)
            self.assertIn("**So far.**", out)
            self.assertEqual(env.fake.requests, [])

    def test_it_is_refused_when_no_week_is_in_progress_or_nothing_is_loaded(self):
        with LivePost() as env:
            rc, out = env.post("live", now=BEFORE_KICKOFF)
            self.assertEqual(rc, 1)
            self.assertIn("no week is in progress", out)
        with LivePost() as env:
            rc, out = env.post("live", now=AFTER_KICKOFF)          # in progress, but no live scores loaded
            self.assertEqual(rc, 1)
            self.assertIn("live-refresh", out)

    def test_a_live_post_is_logged_as_its_own_mode_beside_a_preview(self):
        with LivePost() as env:
            env.live()
            rc, out = env.post("live", now=AFTER_KICKOFF, send_it=True, yes=True)
            self.assertEqual(rc, 0, out)
            self.assertEqual([r[3:5] for r in env.rows()], [("live", "posted")])
            rc, out = env.post("live", now=AFTER_KICKOFF, send_it=True, yes=True)
            self.assertIn("already posted", out)                      # once per week and mode, like the others


if __name__ == "__main__":
    unittest.main()
