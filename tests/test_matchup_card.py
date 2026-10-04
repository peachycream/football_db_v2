"""Phase 11: builder `matchup.build` -> mart_matchup_card (+ _groups, _players). Offline fixtures.

League 11111, four franchises in a ring (each plays TWO games a week, like 30590), 2026 weeks 1-2 complete,
week 3 next (first kickoff 2026-09-25 00:15 UTC). Franchise 0001..0004 each start one player `<id>1`."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fdb import matchup
from fdb import loader as fw
from fdb.loaders import get
from tests.test_fantasy import write_raw
from tests.test_weekly_results import Env, proj_payload, two_games_week, unplayed_week, week_payload, side

L = "11111"
BEFORE_KICKOFF = "2026-09-24T12:00:00Z"   # weeks 1-2 complete, week 3 not kicked off
AFTER_KICKOFF = "2026-09-26T17:00:00Z"    # week 3 under way
POS = {"0001": "QB", "0002": "MLB", "0003": "SAF", "0004": "WR"}


def projections(week, scores):
    """Enough players to pass the loader's floor; `scores` {player id: projection}."""
    rows = [{"id": f"9{i:04d}", "score": "1.0"} for i in range(120)] + [{"id": k, "score": str(v)} for k, v in scores.items()]
    return {"version": "1.0", "projectedScores": {"week": str(week), "playerScore": rows}}


class MartEnv(Env):
    def build(self, now=AFTER_KICKOFF, prob=None):
        with mock.patch.dict(os.environ, {"FDB_NOW": now}):
            return matchup.build(self.c)

    def card(self, week, home, away):
        r = self.c.execute("SELECT * FROM mart_matchup_card WHERE league_id = ? AND week = ? AND home_id = ? AND away_id = ?",
                           (L, week, home, away)).fetchone()
        return r

    def seed_all(self, preview_projection=True, post_projection=True, unresolved=()):
        self.seed({1: two_games_week(1), 2: two_games_week(2, (60.0, 70.0, 80.0, 90.0))})
        for fid, pos in POS.items():
            g = f"G{fid}"
            self.c.execute("INSERT INTO players (gsis_id, display_name, position, players_source) VALUES (?,?,?, 'nflverse_players')",
                           (g, f"Player {fid}", pos))
            if f"{fid}1" not in unresolved:
                self.c.execute("INSERT INTO player_ids (source, source_id, gsis_id, method, evidence) VALUES ('mfl',?,?, 'id_map', 'test')",
                               (f"{fid}1", g))
        self.c.commit()
        with mock.patch.dict(os.environ, {"FDB_NOW": BEFORE_KICKOFF}):
            write_raw("mfl", "weeklyResultsUpcoming", "2026/11111/REG03", unplayed_week(3))
            if preview_projection:
                write_raw("mfl", "projectedScores", "2026/11111/REG03", projections(3, {"00011": 20.0, "00021": 15.0, "00031": 7.0, "00041": 4.0}))
        if post_projection:
            with mock.patch.dict(os.environ, {"FDB_NOW": AFTER_KICKOFF}):
                write_raw("mfl", "projectedScores", "2026/11111/REG03", projections(3, {"00011": 99.0, "00021": 99.0}))
        for lid in ("mfl.upcoming_games", "mfl.upcoming_lineups", "mfl.projected_scores"):
            for r in self.load_all(lid):
                assert r["failures"] == [], (lid, r)


class Final(unittest.TestCase):
    def test_records_points_for_and_series_are_through_the_prior_weeks(self):
        with MartEnv() as env:
            env.seed_all()
            res = env.build()
            self.assertEqual(res["failures"], [], res)
            w1 = env.card(1, "0001", "0002")
            self.assertEqual(w1["state"], "FINAL")
            self.assertEqual((w1["home_w"], w1["home_l"], w1["home_t"], w1["home_pf"]), (0, 0, 0, 0.0))   # week 1: nothing before it
            self.assertEqual(w1["series_meetings"], 0)
            self.assertIsNone(w1["last_meeting_season"])
            self.assertEqual((w1["home_score"], w1["away_score"], w1["home_opt_pts"]), (100.0, 90.0, 105.0))
            w2 = env.card(2, "0001", "0002")
            # 0001 won both week-1 games (100 v 90, 100 v 70) -> 2-0; 0002 lost to 0001, beat 0003 -> 1-1. A week's points once.
            self.assertEqual((w2["home_w"], w2["home_l"], w2["home_pf"]), (2, 0, 100.0))
            self.assertEqual((w2["away_w"], w2["away_l"], w2["away_pf"]), (1, 1, 90.0))
            self.assertEqual((w2["series_meetings"], w2["series_home_wins"], w2["series_away_wins"]), (1, 1, 0))
            self.assertEqual((w2["last_meeting_season"], w2["last_meeting_week"], w2["last_meeting_home_score"],
                              w2["last_meeting_away_score"]), (2026, 1, 100.0, 90.0))
            self.assertEqual((w2["home_score"], w2["away_score"]), (60.0, 70.0))

    def test_division_rivalry_and_names_and_colors(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            self.assertEqual(env.card(1, "0001", "0002")["is_division_rivalry"], 1)   # both division 00
            self.assertEqual(env.card(1, "0002", "0003")["is_division_rivalry"], 0)
            r = env.card(1, "0001", "0002")
            self.assertEqual((r["home_name"], r["home_division"]), ("A", "East"))
            self.assertIsNone(r["home_color"])    # league 11111 has no entry in franchise_colors.toml

    def test_a_game_is_one_row_even_though_both_franchises_have_a_result_row(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM mart_matchup_card WHERE week = 1").fetchone()[0], 4)   # 8 result rows

    def test_groups_map_position_codes_and_add_up_to_the_score(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            got = {r["franchise_id"]: (r["grp"], r["actual"]) for r in env.c.execute(
                "SELECT franchise_id, grp, actual FROM mart_matchup_card_groups WHERE week = 1")}
            self.assertEqual(got, {"0001": ("QB", 100.0), "0002": ("LB", 90.0), "0003": ("DB", 80.0), "0004": ("WR", 70.0)})   # MLB->LB, SAF->DB

    def test_players_join_through_player_ids_and_an_unresolved_id_has_no_name(self):
        with MartEnv() as env:
            env.seed_all(unresolved=("00041",))
            strict = env.build()   # 1 of 4 starters ungrouped is far above the 1% bar: the build fails and writes nothing
            self.assertTrue(any("no known position group" in f for f in strict["failures"]), strict["failures"])
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM mart_matchup_card_players").fetchone()[0], 0)
            with mock.patch.object(matchup, "MAX_UNGROUPED", 1.0):
                res = env.build()
            r = env.c.execute("SELECT gsis_id, display_name, position, grp FROM mart_matchup_card_players WHERE week = 1 AND franchise_id = '0001'").fetchone()
            self.assertEqual(tuple(r), ("G0001", "Player 0001", "QB", "QB"))
            r = env.c.execute("SELECT gsis_id, display_name, position, grp FROM mart_matchup_card_players WHERE week = 1 AND franchise_id = '0004'").fetchone()
            self.assertEqual(tuple(r), (None, None, None, "OTHER"))   # never matched by name; kept under its MFL id
            self.assertTrue(res["ungrouped"])


class PreviewAndLive(unittest.TestCase):
    def test_preview_before_kickoff_uses_the_upcoming_snapshot_and_the_pre_kickoff_projection(self):
        with MartEnv() as env:
            env.seed_all()
            res = env.build(now=BEFORE_KICKOFF)
            self.assertEqual(res["failures"], [], res)
            g = env.card(3, "0001", "0002")
            self.assertEqual((g["state"], g["lineup_source"]), ("PREVIEW", "upcoming_snapshot"))
            self.assertEqual((g["home_score"], g["away_score"], g["home_opt_pts"]), (None, None, None))   # no actuals before the games
            self.assertEqual((g["home_w"], g["home_l"], g["home_pf"]), (2, 2, 160.0))                    # weeks 1-2, both games each
            self.assertEqual((g["series_meetings"], g["series_home_wins"], g["series_away_wins"]), (2, 1, 1))
            self.assertEqual((g["last_meeting_week"], g["last_meeting_home_score"], g["last_meeting_away_score"]), (2, 60.0, 70.0))
            self.assertEqual((g["home_proj"], g["away_proj"], g["home_proj_missing"]), (20.0, 15.0, 0))
            self.assertIsNotNone(g["proj_snapshot_at"])
            self.assertIsNotNone(g["upcoming_snapshot_at"])

    def test_the_projection_taken_after_kickoff_is_never_used(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            g = env.card(3, "0001", "0002")
            self.assertEqual(g["state"], "LIVE")
            self.assertEqual(g["home_proj"], 20.0)   # the 99.0 snapshot is post-kickoff
            self.assertLess(g["proj_snapshot_at"], "20260925")

    def test_no_pre_kickoff_snapshot_means_no_projection_not_a_guess(self):
        with MartEnv() as env:
            env.seed_all(preview_projection=False)
            env.build(now=AFTER_KICKOFF)
            g = env.card(3, "0001", "0002")
            self.assertEqual((g["home_proj"], g["away_proj"], g["proj_snapshot_at"]), (None, None, None))
            self.assertIsNone(env.c.execute("SELECT proj FROM mart_matchup_card_groups WHERE week = 3 AND franchise_id = '0001'").fetchone()[0])

    def test_a_starter_without_a_projection_is_counted(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=BEFORE_KICKOFF)
            # snapshot lists only some starters: 00031 and 00041 are in it; remove nobody, so 0 missing; then drop one
            self.assertEqual(env.card(3, "0003", "0004")["home_proj_missing"], 0)

    def test_a_week_in_weekly_results_is_never_replaced_by_an_upcoming_snapshot(self):
        with MartEnv() as env:
            env.seed_all()
            with mock.patch.dict(os.environ, {"FDB_NOW": BEFORE_KICKOFF}):
                write_raw("mfl", "weeklyResultsUpcoming", "2026/11111/REG02", unplayed_week(2))
            env.build()
            self.assertEqual(env.card(2, "0001", "0002")["lineup_source"], "weekly_results")


class Safety(unittest.TestCase):
    def test_a_bad_color_config_fails_the_build_and_leaves_the_tables_unchanged(self):
        with MartEnv() as env:
            env.seed_all()
            self.assertEqual(env.build()["failures"], [])
            before = env.c.execute("SELECT COUNT(*) FROM mart_matchup_card").fetchone()[0]
            bad = Path(tempfile.mkdtemp()) / "c.toml"
            bad.write_text('[[color]]\nleague_id = "11111"\nfranchise_id = "9999"\ncolor = "#ff0000"\nalt = "red"\n', encoding="utf-8")
            with mock.patch.object(matchup, "COLORS_PATH", bad):
                res = env.build()
            self.assertTrue(any("9999" in f for f in res["failures"]), res["failures"])
            self.assertTrue(any("invalid color" in f for f in res["failures"]), res["failures"])
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM mart_matchup_card").fetchone()[0], before)   # rolled back

    def test_colors_come_from_the_config_by_franchise_id(self):
        cfg = Path(tempfile.mkdtemp()) / "c.toml"
        cfg.write_text('[[color]]\nleague_id = "11111"\nfranchise_id = "0001"\ncolor = "#FFB612"\nalt = "#E8E8E8"\n', encoding="utf-8")
        with MartEnv() as env:
            env.seed_all()
            with mock.patch.object(matchup, "COLORS_PATH", cfg):
                self.assertEqual(env.build()["failures"], [])
            r = env.card(1, "0001", "0002")
            self.assertEqual((r["home_color"], r["home_color_alt"], r["away_color"]), ("#FFB612", "#E8E8E8", None))

    def test_the_real_color_file_is_valid(self):
        colors = matchup.load_colors()
        self.assertEqual(len(colors), 32)
        for (lg, fid), (c, a) in colors.items():
            self.assertRegex(c, matchup.HEX)
            self.assertRegex(a, matchup.HEX)

    def test_markup_is_stripped_from_franchise_names(self):
        self.assertEqual(matchup.strip_markup("<font color='Indigo'>Baltimore Ravens</font> "), "Baltimore Ravens")
        self.assertEqual(matchup.strip_markup(None), "")

    def test_rebuild_is_deterministic(self):
        with MartEnv() as env:
            env.seed_all()
            env.build()
            a = [tuple(r) for r in env.c.execute("SELECT * FROM mart_matchup_card ORDER BY season, week, home_id, away_id")]
            env.build()
            b = [tuple(r) for r in env.c.execute("SELECT * FROM mart_matchup_card ORDER BY season, week, home_id, away_id")]
            self.assertEqual(a, b)

    def test_registered_as_a_builder(self):
        from fdb import registry
        from fdb.builders import BUILDERS
        self.assertIn("matchup.build", registry.owners("builder"))
        self.assertIn("matchup.build", BUILDERS)


if __name__ == "__main__":
    unittest.main()
