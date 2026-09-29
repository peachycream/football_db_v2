"""Phase 7a: dashboard marts (lane / zone / snap-join rules), per-season position, tiles. Offline."""
import unittest

from app import dashboard as d
from fdb import dashboard as builder
from tests.helpers import TempEnv


def _pbp(conn, rows):
    cols = ["game_id", "play_id", "season", "season_type", "week", "load_id", "passer_player_id", "rusher_player_id",
            "receiver_player_id", "qb_dropback", "pass_attempt", "complete_pass", "two_point_attempt", "pass_location",
            "air_yards", "cp", "epa", "success", "rush_attempt", "qb_scramble", "run_location", "run_gap", "yards_gained",
            "yardline_100"]
    base = dict.fromkeys(cols)
    base.update(season=2025, season_type="REG", week=1, load_id="t", qb_dropback=0, pass_attempt=0, complete_pass=0,
                two_point_attempt=0, rush_attempt=0, qb_scramble=0, epa=0.0, success=0, yardline_100=50)
    for i, r in enumerate(rows):
        x = {**base, "game_id": "g", "play_id": i, **r}
        conn.execute(f"INSERT INTO core_pbp ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [x[c] for c in cols])


class Marts(unittest.TestCase):
    def setUp(self):
        self.t = TempEnv().__enter__()
        self.c = self.t.conn()
        self.c.execute("PRAGMA foreign_keys = OFF")   # fixture rows carry no load_log / players parents

    def tearDown(self):
        self.c.close()
        self.t.__exit__(None, None, None)

    def test_lanes_and_zones_follow_v1_rules(self):
        Q, R = "00-QB", "00-RB"
        _pbp(self.c, [
            dict(rush_attempt=1, rusher_player_id=R, run_location="middle", run_gap=None, yards_gained=4),
            dict(rush_attempt=1, rusher_player_id=R, run_location="left", run_gap="tackle", yards_gained=6),
            dict(rush_attempt=1, rusher_player_id=R, run_location="right", run_gap=None, yards_gained=2),   # no lane
            dict(rush_attempt=1, rusher_player_id=Q, qb_scramble=1, run_location="left", run_gap="end"),     # scramble: excluded
            dict(rush_attempt=1, rusher_player_id=R, two_point_attempt=1, run_location="middle"),           # 2-pt: excluded
            dict(qb_dropback=1, pass_attempt=1, complete_pass=1, passer_player_id=Q, pass_location="left", air_yards=-2, cp=0.9),
            dict(qb_dropback=1, pass_attempt=1, passer_player_id=Q, pass_location="middle", air_yards=10, cp=0.5),
            dict(qb_dropback=1, pass_attempt=1, passer_player_id=Q, pass_location="right", air_yards=25, cp=None,
                 receiver_player_id="00-WR", yardline_100=15),
            dict(qb_dropback=1, passer_player_id=Q),                                                       # sack
        ])
        for sql in (builder.QB_DROPBACK, builder.QB_ZONES, builder.RB_LANES):
            self.c.execute(sql)
        lanes = dict(self.c.execute("SELECT lane, carries FROM mart_rb_run_lanes_week"))
        self.assertEqual(lanes, {"M": 1, "LT": 1})
        zones = {(a, b) for a, b in self.c.execute("SELECT zone_direction, zone_depth FROM mart_qb_pass_zones_week")}
        self.assertEqual(zones, {("left", "blos"), ("middle", "medium"), ("right", "deep")})
        db = self.c.execute("SELECT dropbacks, attempts, completions, cpoe_attempts, sum_cp FROM mart_qb_dropback_week").fetchone()
        self.assertEqual(tuple(db), (4, 3, 1, 2, 1.4))   # the sack is a dropback, not an attempt; cp NULL not counted

    def test_player_week_joins_snaps_by_pfr_id_and_keeps_snap_only_weeks(self):
        c = self.c
        c.execute("INSERT INTO player_ids VALUES ('pfr', 'AlleJo02', '00-A', 'source_native', 'x')")
        c.execute("""INSERT INTO core_player_stats (player_id, season, season_type, week, position, targets, load_id)
                     VALUES ('00-A', 2025, 'REG', 1, 'QB', 0, 't'), (NULL, 2025, 'REG', 1, NULL, 0, 't')""")
        c.execute("""INSERT INTO core_snap_counts (game_id, season, season_type, week, pfr_player_id, position, team,
                     offense_snaps, offense_pct, load_id) VALUES ('g1', 2025, 'REG', 1, 'AlleJo02', 'QB', 'BUF', 60, 1.0, 't'),
                     ('g18', 2025, 'REG', 18, 'AlleJo02', 'QB', 'BUF', 1, 0.02, 't')""")
        c.execute(builder.PLAYER_WEEK)
        rows = c.execute("SELECT week, offense_snaps, targets FROM mart_player_week ORDER BY week").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(1, 60, 0), (18, 1, None)])   # nameless team row dropped; wk18 kept
        self.assertEqual(builder.checks(c), [])


class Positions(unittest.TestCase):
    def test_label_maps(self):
        self.assertEqual(d._bucket("SAF"), ("defense", "S"))
        self.assertEqual(d._bucket("ED"), ("defense", "DE"))
        self.assertEqual(d._bucket("FB"), ("offense", "RB"))
        self.assertEqual(d._bucket("K"), (None, None))

    def test_season_position_prefers_pff_defense_unless_offense(self):
        with TempEnv() as t:
            c = t.conn()
            c.execute("PRAGMA foreign_keys = OFF")
            c.executemany("INSERT INTO player_ids VALUES ('pff', ?, ?, 'source_native', 'x')", [("1", "00-S"), ("2", "00-FB")])
            c.executemany("""INSERT INTO core_pff_defense_season (season, weeks_requested, player_id, position, snap_counts_defense, load_id)
                             VALUES (2025, 'x', ?, ?, 300, 't')""", [(1, "S"), (2, "DI")])
            c.executemany("""INSERT INTO mart_player_week (season, season_type, week, gsis_id, position)
                             VALUES (2025, 'REG', ?, ?, ?)""", [(3, "00-S", "CB"), (4, "00-FB", "FB")])
            pos = d.season_positions(c, 2025)
            self.assertEqual(pos["00-S"], ("defense", "S", "S"))      # PFF's safety, not nflverse's weekly CB label
            self.assertEqual(pos["00-FB"], ("offense", "RB", "FB"))   # a DT converted to FB plays offense that season
            c.close()


class Values(unittest.TestCase):
    def test_default_idp_split(self):
        row = {"tackles": 4, "assists": 2, "tackles_for_loss": 0, "sacks": 1, "hits": 0, "interceptions": 0,
               "pass_break_ups": 0, "forced_fumbles": 0, "fumble_recoveries": 0}
        total, share = d.default_idp(row)
        self.assertAlmostEqual(total, 4 * 1.25 + 2 * 0.75 + 5)
        self.assertAlmostEqual(share, 100 * 5 / total)

    def test_passer_rating_perfect_and_none(self):
        self.assertAlmostEqual(d._passer_rating(20, 20, 400, 5, 0), 158.33, places=2)
        self.assertIsNone(d._passer_rating(0, 0, 0, 0, 0))

    def test_league_id_parsing(self):
        self.assertEqual(d._league("mfl:30590:2026"), ("mfl", "30590"))
        self.assertEqual(d._league("sleeper:123"), ("sleeper", "123"))
        self.assertEqual(d._league("default"), (None, None))

    def test_every_bucket_has_nine_tiles_and_pending_is_labelled(self):
        for b, specs in d.TILE_SPECS.items():
            self.assertEqual(sorted(s["n"] for s in specs), list(range(1, 10)), b)
        # 7b: expected tackles passed §6.1's gate and is live; the three expected-SACK tiles stay pending
        self.assertEqual([s["label"] for s in d.TILE_SPECS["DE"] if s["kind"] == "pending"],
                         ["Exp Sack %ile", "Exp Sacks/G", "Sacks vs Exp"])
        self.assertFalse(any(s["kind"] == "pending" for b in ("LB", "CB", "S") for s in d.TILE_SPECS[b]))


class Apis(unittest.TestCase):
    def setUp(self):
        self.t = TempEnv().__enter__()
        self.t.conn().close()
        from app import create_app
        self.c = create_app().test_client()

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_routes_validate_and_404(self):
        for ep in ("header", "tiles", "snaps", "routes", "qb-zones", "rb-lanes", "idp-alignment", "available-seasons"):
            self.assertEqual(self.c.get(f"/api/dashboard/{ep}").status_code, 400, ep)
            self.assertEqual(self.c.get(f"/api/dashboard/{ep}?player_id=00-X&season=2025").status_code, 404, ep)
        self.assertEqual(self.c.get("/api/dashboard/search?q=a").get_json(), [])
        self.assertEqual(self.c.get("/api/dashboard/leagues").status_code, 200)
        self.assertEqual(self.c.get("/viz/player").status_code, 200)


if __name__ == "__main__":
    unittest.main()
