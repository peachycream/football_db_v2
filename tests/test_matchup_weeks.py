"""Phase 11: which week a recap and a preview are about (fdb/matchup_weeks.py), and the builder rule behind it: FINAL means
the results are LOADED. v1 used one "current week" for both modes, so a Monday recap targeted the unplayed week 4.

Fixture: league 11111, 2026 weeks 1-2 loaded; week 3 first kicks off 2026-09-25 00:15 UTC and is complete 2026-09-29 ~04:15 UTC."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fdb import card_render as cr
from fdb import matchup_weeks as mw
from tests.test_matchup_card import AFTER_KICKOFF, BEFORE_KICKOFF, L, MartEnv
from tests.test_matchup_page import client
from tests.test_weekly_results import two_games_week
from tests.test_fantasy import write_raw

WEEK3_COMPLETE_NOT_LOADED = "2026-09-30T12:00:00Z"   # the schedule says week 3 is over; its results are not loaded


def finish_week3_in_the_schedule(env):
    """The fixture schedule has no scores for week 3 (it is in the future there); give its games results."""
    env.c.execute("UPDATE core_schedule SET result = 3 WHERE season = 2026 AND season_type = 'REG' AND week = 3")
    env.c.commit()


class Recap(unittest.TestCase):
    def test_while_a_week_is_under_way_the_recap_is_the_previous_week_and_says_what_it_waits_for(self):
        """The v1 bug: a recap run while week 3 is in progress must be about week 2, never week 3."""
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            t = mw.recap_target(env.c, L)
            self.assertEqual((t["ready"], t["week"], t["state"], t["waiting_for"]), (True, 2, "FINAL", 3))
            self.assertIn("week 3 is in progress", t["reason"])
            self.assertIsNotNone(t["featured"])

    def test_before_the_next_week_kicks_off_the_recap_is_the_latest_week_with_results(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            t = mw.recap_target(env.c, L)
            self.assertEqual((t["ready"], t["week"], t["waiting_for"], t["reason"]), (True, 2, None, None))

    def test_no_results_means_not_ready_with_a_reason(self):
        with MartEnv() as env:
            env.c.commit()
            t = mw.recap_target(env.c)
            self.assertEqual((t["ready"], t["week"], t["reason"]), (False, None, "no matchup data yet"))

    def test_playoff_weeks_are_flagged_not_hidden(self):
        with MartEnv() as env:
            env.seed_all()
            env.c.execute("UPDATE core_mfl_league SET lastRegularSeasonWeek = 1")
            env.c.commit()
            env.build(now=BEFORE_KICKOFF)
            self.assertTrue(mw.recap_target(env.c, L)["is_playoff"])


class Scope(unittest.TestCase):
    def test_a_named_league_or_season_without_data_is_not_replaced_by_another(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            for fn in (mw.recap_target, mw.preview_target):
                t = fn(env.c, "55757")
                self.assertEqual((t["ready"], t["week"]), (False, None))
                self.assertEqual(t["reason"], "no matchup data for league 55757")
                t = fn(env.c, L, 2019)
                self.assertEqual((t["ready"], t["week"]), (False, None))
                self.assertIn("season 2019", t["reason"])
            self.assertTrue(mw.recap_target(env.c)["ready"])            # unnamed league and season default
            self.assertTrue(mw.recap_target(env.c, L, 2026)["ready"])


class Preview(unittest.TestCase):
    def test_before_kickoff_the_preview_is_the_next_week_and_ready(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            t = mw.preview_target(env.c, L)
            self.assertEqual((t["ready"], t["week"], t["state"], t["projected"], t["reason"]), (True, 3, "PREVIEW", True, None))
            self.assertEqual(t["featured"]["basis"], "projection")

    def test_after_kickoff_a_preview_is_not_possible(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            t = mw.preview_target(env.c, L)
            self.assertEqual((t["ready"], t["week"], t["state"]), (False, 3, "LIVE"))
            self.assertIn("already kicked off", t["reason"])

    def test_a_preview_without_a_pre_kickoff_projection_is_ready_but_says_so(self):
        with MartEnv() as env:
            env.seed_all(preview_projection=False, post_projection=False)
            env.build(now=BEFORE_KICKOFF)
            t = mw.preview_target(env.c, L)
            self.assertEqual((t["ready"], t["projected"]), (True, False))
            self.assertIn("no projection was captured before kickoff", t["reason"])

    def test_missing_lineups_are_named_as_the_reason_not_a_missing_projection(self):
        """A projection snapshot exists but a franchise has no lineup yet: say THAT, not "no projection was captured"."""
        with MartEnv() as env:
            env.seed_all()
            env.c.execute("DELETE FROM core_mfl_upcoming_lineups WHERE franchise_id IN ('0001', '0002')")
            env.c.commit()
            env.build(now=BEFORE_KICKOFF)
            t = mw.preview_target(env.c, L)
            self.assertEqual((t["ready"], t["projected"]), (True, False))
            self.assertIn("have a side with no lineup yet", t["reason"])
            self.assertNotIn("no projection was captured", t["reason"])
            self.assertIn("3 of 4 games", t["reason"])                              # every game touches 0001 or 0002 except 0003 v 0004

    def test_the_recap_and_the_preview_are_different_weeks(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            self.assertNotEqual(mw.recap_target(env.c, L)["week"], mw.preview_target(env.c, L)["week"])

    def test_nothing_to_preview_when_every_week_has_results(self):
        with MartEnv() as env:
            env.seed_all()
            finish_week3_in_the_schedule(env)
            self._load_week3_results(env)
            env.build(now=WEEK3_COMPLETE_NOT_LOADED)
            t = mw.preview_target(env.c, L)
            self.assertEqual((t["ready"], t["week"]), (False, None))
            self.assertIn("no upcoming week", t["reason"])
            self.assertEqual(mw.recap_target(env.c, L)["week"], 3)   # and the recap has moved on to week 3

    @staticmethod
    def _load_week3_results(env):
        with mock.patch.dict(os.environ, {"FDB_NOW": WEEK3_COMPLETE_NOT_LOADED}):
            write_raw("mfl", "weeklyResults", f"2026/{L}/REG03", two_games_week(3, (70.0, 80.0, 90.0, 100.0)))
            for lid in ("mfl.weekly_results", "mfl.lineups"):
                for r in env.load_all(lid):
                    assert r["failures"] == [], (lid, r)


class ResultsNotLoadedYet(unittest.TestCase):
    """Complete per the schedule, results not loaded (Wednesday 00:15 to 05:00 ET): the mart must neither fail nor lie."""

    def test_the_build_passes_and_the_week_stays_live(self):
        with MartEnv() as env:
            env.seed_all()
            finish_week3_in_the_schedule(env)
            res = env.build(now=WEEK3_COMPLETE_NOT_LOADED)
            self.assertEqual(res["failures"], [], res)
            self.assertIn("4 complete-per-schedule games awaiting their results", res["summary"])
            g = env.card(3, "0001", "0002")
            self.assertEqual((g["state"], g["lineup_source"], g["home_score"], g["away_score"]), ("LIVE", "upcoming_snapshot", None, None))

    def test_the_recap_waits_and_the_preview_is_refused(self):
        with MartEnv() as env:
            env.seed_all()
            finish_week3_in_the_schedule(env)
            env.build(now=WEEK3_COMPLETE_NOT_LOADED)
            r, p = mw.recap_target(env.c, L), mw.preview_target(env.c, L)
            self.assertEqual((r["week"], r["waiting_for"]), (2, 3))
            self.assertFalse(p["ready"])

    def test_once_the_results_load_the_week_is_final_and_the_recap_moves_on(self):
        with MartEnv() as env:
            env.seed_all()
            finish_week3_in_the_schedule(env)
            Preview._load_week3_results(env)
            res = env.build(now=WEEK3_COMPLETE_NOT_LOADED)
            self.assertEqual(res["failures"], [], res)
            self.assertEqual(env.card(3, "0001", "0002")["state"], "FINAL")
            self.assertEqual(mw.recap_target(env.c, L)["week"], 3)


class Surfaces(unittest.TestCase):
    def test_render_by_mode_uses_the_target_and_refuses_when_not_ready(self):
        out = Path(tempfile.mkdtemp(prefix="fdb_mode_")) / "x.png"
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            with mock.patch.object(cr, "render_png", return_value=b"\x89PNG fake") as rp:
                path, card = cr.render_to_file(env.c, L, mode="recap", out=out)
                self.assertEqual((card["week"], card["state"]), (2, "FINAL"))
                path, card = cr.render_to_file(env.c, L, mode="preview", out=out)
                self.assertEqual((card["week"], card["state"]), (3, "PREVIEW"))
            self.assertEqual(rp.call_count, 2)
            with self.assertRaises(cr.RenderError) as cm:
                cr.render_to_file(env.c, L, week=2, mode="recap")
            self.assertIn("do not combine", str(cm.exception))
            env.build(now=AFTER_KICKOFF)
            with mock.patch.object(cr, "render_png") as rp2:
                with self.assertRaises(cr.RenderError) as cm:
                    cr.render_to_file(env.c, L, mode="preview")
                rp2.assert_not_called()                      # never renders the wrong week
            self.assertIn("already kicked off", str(cm.exception))

    def test_cli_mode_exits_nonzero_with_the_reason(self):
        import io
        from fdb import __main__ as cli
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = cli.main(["card", "--league", L, "--mode", "preview"])
            self.assertEqual(rc, 1)
            self.assertIn("preview: week 3 has already kicked off", buf.getvalue())

    def test_page_lists_what_a_job_would_post(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            body = client().get("/matchup/").data.decode()
            self.assertIn("WHAT A JOB WOULD POST", body)
            self.assertIn("Recap</b>:", body)
            self.assertIn("week 2</a> (ready)", body)
            self.assertIn("week 3</a> (not ready)", body)
            self.assertIn("already kicked off", body)



class Refresh(unittest.TestCase):
    """`fdb matchup-refresh`: the three pre-game loaders, then the builder, then what is ready. Posts nothing."""

    def run_refresh(self, env, now, results=None):
        import contextlib
        import io
        from fdb import matchup_refresh, weekly
        calls = []

        def fake(conn, lid):
            calls.append(lid)
            return (results or {}).get(lid, {"loader": lid, "fetched": 1, "cached": 0, "loaded": 2, "failures": [], "rc": 0})
        buf = io.StringIO()
        with mock.patch.object(weekly, "run_loader", fake), mock.patch.dict(os.environ, {"FDB_NOW": now}), contextlib.redirect_stdout(buf):
            rc = matchup_refresh.run(env.c, L)
        return rc, buf.getvalue(), calls

    def test_runs_the_three_pre_game_loaders_in_order_then_builds_and_reports(self):
        from fdb import matchup_refresh
        with MartEnv() as env:
            env.seed_all()
            rc, out, calls = self.run_refresh(env, BEFORE_KICKOFF)
            self.assertEqual(calls, list(matchup_refresh.LOADERS))
            self.assertEqual(rc, 0, out)
            self.assertIn("matchup.build:", out)
            self.assertIn("recap: week 2 ready", out)
            self.assertIn("preview: week 3 ready", out)

    def test_a_failing_loader_is_a_nonzero_exit_but_it_still_builds_and_reports(self):
        with MartEnv() as env:
            env.seed_all()
            bad = {"mfl.projected_scores": {"loader": "mfl.projected_scores", "fetched": 0, "cached": 0, "loaded": 0,
                                            "failures": ["fetch 2026/11111/REG03: HTTP 429"], "rc": 1}}
            rc, out, calls = self.run_refresh(env, BEFORE_KICKOFF, bad)
            self.assertEqual(rc, 1)
            self.assertIn("FAILED 1", out)
            self.assertIn("matchup.build:", out)
            self.assertEqual(len(calls), 3)

    def test_after_kickoff_it_says_the_new_projection_will_not_be_used(self):
        with MartEnv() as env:
            env.seed_all()
            rc, out, _ = self.run_refresh(env, AFTER_KICKOFF)
            self.assertIn("already kicked off", out)
            self.assertIn("will NOT be used", out)

    def test_it_never_posts(self):
        import inspect
        from fdb import matchup_refresh
        src = inspect.getsource(matchup_refresh)
        self.assertNotIn("discord_post", src)
        self.assertNotIn("send(", src)


if __name__ == "__main__":
    unittest.main()
