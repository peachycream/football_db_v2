"""Phase 11/12: two source facts the Wednesday weekly run of 2026-10-07 hit, found by its failures.

1. nflverse REMOVED the plain `games.csv` asset from its `schedules` release (HTTP 404); the same table is now `games.csv.gz`.
   The loader asks for the gz, stores it as received, and reads gzip OR plain CSV by magic bytes, so raw files fetched before the
   change still replay in `fdb rebuild`.
2. The injuries loader demanded >= 50 rows for every regular-season week, but the NEWEST week's report is published gradually from
   Wednesday (week 5 had 19 rows that morning). Only the newest week is exempt from the floor; earlier weeks and the ceiling stay."""
import gzip
import unittest
from unittest import mock

from fdb import http, loader as fw, raw
from fdb.loader import Scope
from fdb.loaders import get
from fdb.loaders import nflverse_schedules as ns
from fdb.loaders.injuries import NflInjuriesLoader
from tests.helpers import FIXTURES, TempEnv, seed_schedule_raw

FIXTURE = (FIXTURES / "games_2025_2026.csv").read_bytes()


class SchedulesGzip(unittest.TestCase):
    def test_it_asks_for_the_gz_asset_and_stores_it_as_received(self):
        self.assertTrue(ns.URL.endswith("/schedules/games.csv.gz"))
        ld = get("nflverse.schedules")
        self.assertEqual(ld.ext, "csv.gz")
        gz = gzip.compress(FIXTURE)
        with mock.patch.object(http, "get", return_value=gz) as g:
            body, params = ld.fetch("all")
        g.assert_called_once_with(ns.URL)
        self.assertEqual(body, gz)                       # raw = exactly what the server sent
        self.assertEqual(params, {"url": ns.URL})

    def test_gzip_and_plain_csv_parse_to_the_same_rows(self):
        ld = get("nflverse.schedules")
        plain_fields, plain_rows = ld.parse(FIXTURE)
        gz_fields, gz_rows = ld.parse(gzip.compress(FIXTURE))
        self.assertEqual(plain_fields, gz_fields)
        self.assertEqual(plain_rows, gz_rows)
        self.assertGreater(len(plain_rows), 100)

    def test_a_gzip_raw_file_loads_exactly_like_a_plain_one(self):
        """The new asset through the real framework (raw store -> load), and the old raw format still replays."""
        counts = {}
        for name, payload, ext in (("plain", FIXTURE, "csv"), ("gz", gzip.compress(FIXTURE), "csv.gz")):
            with TempEnv() as env:
                raw.write("nflverse", "schedules", "all", payload, ext, {"fixture": True}, 1, False)
                c = env.conn()
                ld = get("nflverse.schedules")
                for sc in fw.scopes(c, ld):
                    res = fw.load(c, ld, sc, apply=True)
                    self.assertEqual(res["failures"], [], (name, res))
                counts[name] = c.execute("SELECT COUNT(*) FROM core_schedule").fetchone()[0]
        self.assertEqual(counts["plain"], counts["gz"])
        self.assertGreater(counts["gz"], 0)

    def test_a_new_gz_fetch_replaces_an_older_plain_one_as_the_latest_raw(self):
        with TempEnv():
            raw.write("nflverse", "schedules", "all", FIXTURE, "csv", {"fixture": True}, 1, False)
            with mock.patch.dict("os.environ", {"FDB_NOW": "2099-01-01T00:00:00Z"}):
                newer = raw.write("nflverse", "schedules", "all", gzip.compress(FIXTURE), "csv.gz", {"fixture": True}, 1, False)
            latest = raw.latest("nflverse", "schedules", "all")
            self.assertEqual(latest.path, newer.path)
            self.assertEqual(get("nflverse.schedules").parse(latest.read_bytes())[1],
                             get("nflverse.schedules").parse(FIXTURE)[1])


def add_week(c, season, week, n, load_id, season_type="REG"):
    for i in range(n):
        c.execute("""INSERT INTO core_nflverse_injuries (season, season_type, team, week, gsis_id, load_id)
                     VALUES (?, ?, 'KC', ?, ?, ?)""", (season, season_type, week, f"00-{week:02d}{i:05d}", load_id))


class InjuriesNewestWeek(unittest.TestCase):
    def run_checks(self, weeks):
        """weeks: {week: rows}; returns the row-count failures the loader reports for 2026."""
        with TempEnv() as env:
            c = env.conn()
            c.execute("BEGIN")
            c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('t','t','t','t',0)")
            for w, n in weeks.items():
                add_week(c, 2026, w, n, 1)
            fails = NflInjuriesLoader().checks(c, Scope(2026))
            c.execute("ROLLBACK")
        return [f for f in fails if "implausible row counts" in f]

    def test_the_newest_week_may_be_short_while_its_report_is_still_being_published(self):
        """The 2026-10-07 case: weeks 1-4 complete, week 5 has 19 rows on Wednesday morning."""
        self.assertEqual(self.run_checks({1: 60, 2: 60, 3: 60, 4: 60, 5: 19}), [])

    def test_an_earlier_short_week_still_fails(self):
        fails = self.run_checks({1: 60, 2: 10, 3: 60, 4: 60, 5: 19})
        self.assertEqual(len(fails), 1)
        self.assertIn("('REG', 2, 10)", fails[0])
        self.assertNotIn("('REG', 5", fails[0])                       # the newest week is not what failed

    def test_the_floor_applies_to_a_week_as_soon_as_a_later_week_appears(self):
        fails = self.run_checks({1: 60, 2: 60, 3: 60, 4: 60, 5: 19, 6: 5})
        self.assertEqual(len(fails), 1)
        self.assertIn("('REG', 5, 19)", fails[0])                      # week 5 is no longer the newest

    def test_the_ceiling_still_applies_to_every_week_including_the_newest(self):
        fails = self.run_checks({1: 60, 2: 60, 3: 60, 4: 60, 5: 701})
        self.assertEqual(len(fails), 1)
        self.assertIn("('REG', 5, 701)", fails[0])

    def test_a_season_with_a_single_short_week_is_the_newest_week(self):
        self.assertEqual(self.run_checks({1: 19}), [])


class DashboardRouteTree(unittest.TestCase):
    """The route-tree check (fdb/dashboard.py route_tree_fails) when FTN has published a game's plays but not its route charting.
    The real case, 2026 week 4: 15 of 16 games charted, 967 route targets against nflverse's 1,046 (92.4%)."""

    def db(self, routed_games, total_games=16, nfl_targets=1046, ftn_targets=967, week=4):
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.executescript("""CREATE TABLE mart_player_routes_week (season INT, season_type TEXT, week INT, targets INT);
                           CREATE TABLE core_player_stats (season INT, season_type TEXT, week INT, targets INT);
                           CREATE TABLE core_ftn_participation (season INT, season_type TEXT, week INT, gid INT, route1 TEXT);""")
        c.execute("INSERT INTO mart_player_routes_week VALUES (2026, 'REG', ?, ?)", (week, ftn_targets))
        c.execute("INSERT INTO core_player_stats VALUES (2026, 'REG', ?, ?)", (week, nfl_targets))
        for g in range(total_games):
            for p in range(5):
                c.execute("INSERT INTO core_ftn_participation VALUES (2026, 'REG', ?, ?, ?)",
                          (week, 7000 + g, "Go" if (g < routed_games and p < 3) else (None if p % 2 else "")))
        return c

    def test_the_real_case_passes_as_pending_not_as_a_clean_pass(self):
        from fdb import dashboard
        pending = []
        self.assertEqual(dashboard.route_tree_fails(self.db(routed_games=15), pending), [])
        self.assertEqual(len(pending), 1)
        self.assertIn("2026 REG4: route charting pending for 1 of 16 FTN games", pending[0])

    def test_with_every_game_charted_the_old_floor_still_applies(self):
        from fdb import dashboard
        fails = dashboard.route_tree_fails(self.db(routed_games=16), [])
        self.assertEqual(len(fails), 1)
        self.assertIn("route-tree targets 967 vs nflverse 1046", fails[0])
        self.assertEqual(dashboard.route_tree_fails(self.db(routed_games=16, ftn_targets=1030), []), [])   # 98.5%: fine

    def test_a_bigger_shortfall_than_the_uncharted_game_explains_still_fails(self):
        from fdb import dashboard
        pending = []
        fails = dashboard.route_tree_fails(self.db(routed_games=15, ftn_targets=800), pending)   # 76.5% of 1,046
        self.assertEqual(len(fails), 1)
        self.assertIn("1 of 16 FTN games have no route charting yet", fails[0])
        self.assertEqual(pending, [])                                   # a failure is not also a pending note

    def test_the_ceiling_is_unchanged_by_uncharted_games(self):
        from fdb import dashboard
        fails = dashboard.route_tree_fails(self.db(routed_games=15, ftn_targets=1100), [])        # 105%
        self.assertEqual(len(fails), 1)

    def test_a_week_with_no_ftn_rows_keeps_the_original_tolerance(self):
        from fdb import dashboard
        c = self.db(routed_games=0, total_games=0)
        self.assertEqual(len(dashboard.route_tree_fails(c, [])), 1)                                 # 92% and no allowance

    def test_pending_is_optional(self):
        from fdb import dashboard
        self.assertEqual(dashboard.route_tree_fails(self.db(routed_games=15)), [])

    def test_the_builder_result_carries_pending_so_the_weekly_job_reports_it(self):
        import inspect
        from fdb import dashboard
        src = inspect.getsource(dashboard.build)
        self.assertIn('out["pending"] = pending', src)


if __name__ == "__main__":
    unittest.main()
