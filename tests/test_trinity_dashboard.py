"""Trinity on the Player Dashboard: the WR tile, /api/dashboard/trinity and mart_trinity_season_stored. Offline."""
import os
import unittest
from unittest import mock

from app import dashboard as d
from fdb import loader as fw
from fdb.loaders.nflverse_schedules import ScheduleLoader
from tests.helpers import TempEnv, seed_schedule_raw

NOW = "2027-02-20T12:00:00Z"        # 2025 is a closed season in the schedule fixture
COLS = ("season, season_type, week, sleeper_id, player_gsis_id, gsis_id, full_name, team, position, games, routes, targets, rec, "
        "rec_yards, rec_td, first_downs, yprr, rec_per_game, yac_per_game, air_yard_share, z_first_downs, z_yprr, z_yac_per_game, "
        "z_rec_per_game, z_air_yard_share, trinity_score, tier, position_rank")


def trow(season, week, gsis, pos, score, tier, rank, team="KC", games=1):
    return (season, "REG", week, f"s-{gsis}", f"dd-{gsis}", gsis, gsis, team, pos, games, 30, 8, 5, 70, 1, 3,
            2.3, 5.0, 12.0, 0.3, 0.1, 0.2, 0.3, 0.4, 0.5, score, tier, rank)


class Env(TempEnv):
    def __enter__(self):
        super().__enter__()
        self.p = mock.patch.dict(os.environ, {"FDB_NOW": NOW})
        self.p.start()
        self.c = self.conn()
        self.c.execute("PRAGMA foreign_keys = OFF")        # fixture rows carry no load_log / players parents
        seed_schedule_raw()
        ld = ScheduleLoader()
        for sc in fw.scopes(self.c, ld):
            assert not fw.load(self.c, ld, sc, apply=True)["failures"]
        return self

    def __exit__(self, *exc):
        self.p.stop()
        return super().__exit__(*exc)

    def player(self, gsis, pos, name=None):
        self.c.execute("INSERT INTO players (gsis_id, display_name, players_source, position) VALUES (?, ?, 'nflverse_players', ?)",
                       (gsis, name or gsis, pos))
        for season in (2020, 2025):
            self.c.execute("INSERT INTO mart_player_week (season, season_type, week, gsis_id, position) VALUES (?, 'REG', 1, ?, ?)",
                           (season, gsis, pos))

    def trinity(self, rows, table="mart_trinity_week"):
        self.c.executemany(f"INSERT INTO {table} ({COLS}) VALUES ({','.join('?' * 28)})", rows)


class Spec(unittest.TestCase):
    def test_wr_tile_9_is_trinity_and_inside_20_is_gone(self):
        wr = {s["n"]: s for s in d.TILE_SPECS["WR"]}
        self.assertEqual((wr[9]["label"], wr[9]["kind"], wr[9]["fmt"]), ("Trinity Score", "trinity", "x2"))
        self.assertNotIn("Inside-20 Tgts", [s["label"] for s in d.TILE_SPECS["WR"]])
        for b, specs in d.TILE_SPECS.items():
            self.assertEqual(sorted(s["n"] for s in specs), list(range(1, 10)), b)       # still a 3x3 everywhere
        # the user asked for the WR tile; TE and RB keep every tile they had
        self.assertNotIn("Trinity Score", [s["label"] for b in ("TE", "RB", "QB") for s in d.TILE_SPECS[b]])

    def test_tile_bands_are_the_pages(self):
        self.assertEqual([m for _, m in d.TRINITY_BANDS["WR"]], [7.7, 6.7, 5.5, 4.9])
        self.assertEqual([m for _, m in d.TRINITY_BANDS["TE"]], [7.2, 6.6, 5.5, 5.1])


class Panel(unittest.TestCase):
    def setUp(self):
        self.e = Env().__enter__()
        self.addCleanup(self.e.__exit__, None, None, None)
        e = self.e
        e.player("00-WR1", "WR", "Wide One"); e.player("00-WR2", "WR"); e.player("00-TE1", "TE"); e.player("00-RB1", "RB"); e.player("00-QB1", "QB")
        # 2025: weeks 1-13 loaded, 14-17 withheld (the 2024-style source defect), WR1 has no row in week 4 (bye)
        wk = [trow(2025, w, "00-WR1", "WR", 5.0 + w / 10, "League Average", 3) for w in range(1, 14) if w != 4]
        wk += [trow(2025, w, "00-WR2", "WR", 4.0, "Depth", 9) for w in range(1, 14)]
        wk += [trow(2025, 1, "00-TE1", "TE", 7.3, "Elite", 1), trow(2025, 1, "00-RB1", "RB", 7.8, "Elite", 1)]
        e.trinity(wk)
        e.trinity([trow(2025, 13, "00-WR1", "WR", 6.4, "League Average", 2, games=12), trow(2025, 13, "00-WR2", "WR", 4.4, "Depth", 8),
                   trow(2025, 13, "00-TE1", "TE", 7.0, "Above League Average", 2), trow(2025, 13, "00-RB1", "RB", 7.1, "Above League Average", 2)],
                  table="mart_trinity_through_week")
        # DD's stored scores: WR1 once, WR2 twice (DD builds by name, so one sleeper id sits on two rows)
        e.c.executemany("INSERT INTO player_ids VALUES ('sleeper', ?, ?, 'source_native', 't')", [("s-00-WR1", "00-WR1"), ("s-00-WR2", "00-WR2")])
        for name, sid, score in (("Wide One", "s-00-WR1", 6.5), ("Wide Two", "s-00-WR2", 4.5), ("W. Two", "s-00-WR2", 3.9)):
            e.c.execute("""INSERT INTO core_trinity_scores (season, season_type, player_name, position, team, sleeper_id, trinity_score, tier, rank, load_id)
                           VALUES (2025, 'REG', ?, 'WR', 'KC', ?, ?, 'League Average', 12, 't')""", (name, sid, score))
        from app import create_app
        self.c = create_app().test_client()

    def get(self, pid, season=2025):
        return self.c.get(f"/api/dashboard/trinity?player_id={pid}&season={season}").get_json()

    def test_validates_and_404s(self):
        self.assertEqual(self.c.get("/api/dashboard/trinity").status_code, 400)
        self.assertEqual(self.c.get("/api/dashboard/trinity?player_id=00-NOPE&season=2025").status_code, 404)

    def test_weekly_series_summary_and_stored(self):
        j = self.get("00-WR1")
        self.assertTrue(j["supported"] and j["has_data"])
        self.assertEqual([w["week"] for w in j["weekly"]], [w for w in range(1, 14) if w != 4])    # the bye is a gap, not a zero
        self.assertEqual(j["weekly"][0]["score"], 5.1)
        s = j["summary"]
        self.assertEqual((s["week"], s["score"], s["tier"], s["rank"], s["pool"], s["games"]), (13, 6.4, "League Average", 2, 2, 12))
        self.assertEqual(j["stored"]["score"], 6.5)                                                 # DD's own number, labelled separately
        self.assertEqual([b["min"] for b in j["bands"]], [7.7, 6.7, 5.5, 4.9])

    def test_weeks_the_league_played_but_dd_lacks_are_named(self):
        self.assertEqual(self.get("00-WR1")["withheld_weeks"], [14, 15, 16, 17])

    def test_a_dd_id_stored_twice_gets_no_stored_score(self):
        """DD builds its stored score by name: two rows on one sleeper id is ambiguous, so the view drops both."""
        self.assertIsNone(self.get("00-WR2")["stored"])
        self.assertEqual(self.e.c.execute("SELECT COUNT(*) FROM mart_trinity_season_stored WHERE sleeper_id = 's-00-WR2'").fetchone()[0], 0)
        self.assertEqual(self.e.c.execute("SELECT COUNT(*) FROM mart_trinity_season_stored WHERE sleeper_id = 's-00-WR1'").fetchone()[0], 1)

    def test_te_uses_te_bands_and_rb_uses_wr_bands(self):
        self.assertEqual([b["min"] for b in self.get("00-TE1")["bands"]], [7.2, 6.6, 5.5, 5.1])
        self.assertEqual([b["min"] for b in self.get("00-RB1")["bands"]], [7.7, 6.7, 5.5, 4.9])

    def test_qb_is_unsupported_and_seasons_before_2021_say_so(self):
        q = self.get("00-QB1")
        self.assertFalse(q["supported"])
        self.assertEqual((q["weekly"], q["through"], q["has_data"]), ([], [], False))
        old = self.get("00-WR1", season=2020)
        self.assertEqual((old["supported"], old["has_data"], old["first_season"]), (True, False, 2021))

    def test_a_player_without_a_score_has_no_data_not_an_error(self):
        self.e.player("00-WR3", "WR")
        j = self.get("00-WR3")
        self.assertEqual((j["supported"], j["has_data"], j["summary"], j["stored"]), (True, False, None, None))
        self.assertEqual(j["withheld_weeks"], [14, 15, 16, 17])      # a season-level fact, still reported


class Tile(unittest.TestCase):
    def test_value_is_season_to_date_at_the_latest_scored_week_by_gsis(self):
        with Env() as e:
            e.player("00-WR1", "WR")
            e.trinity([trow(2025, 12, "00-WR1", "WR", 5.0, "League Average", 5), trow(2025, 13, "00-WR1", "WR", 6.4, "League Average", 2)],
                      table="mart_trinity_through_week")
            spec = {"kind": "trinity"}
            vm = d._value_map(e.c, 2025, spec, ["00-WR1", "00-NONE"], {}, "default")
            self.assertEqual(vm, {"00-WR1": 6.4})                                   # the last week, not an average of weeks
            self.assertEqual(d._trinity_tile(e.c, 2025, "00-WR1", 6.4, "6.40"), ("6.40", "League Average · WR2 · thru wk 13"))
            self.assertEqual(d._trinity_tile(e.c, 2020, "00-WR1", None, "n/a"), ("—", "Trinity data starts in 2021"))
            disp, sub = d._trinity_tile(e.c, 2025, "00-NONE", None, "n/a")
            self.assertEqual(disp, "n/a")
            self.assertIn("target floor", sub)


if __name__ == "__main__":
    unittest.main()
