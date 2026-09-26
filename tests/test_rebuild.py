import unittest

from fdb import config, db, http, rebuild
from tests.helpers import TempEnv, seed_schedule_raw


class Rebuild(unittest.TestCase):
    def test_rebuild_twice_identical_and_offline(self):
        with TempEnv():
            seed_schedule_raw()
            calls = http.CALLS
            self.assertEqual(rebuild.run(), 0)
            h1 = db.content_hash(db.connect())
            self.assertEqual(rebuild.run(), 0)
            h2 = db.content_hash(db.connect())
            self.assertEqual(h1, h2)
            self.assertEqual(http.CALLS, calls)
            self.assertEqual(db.connect().execute("SELECT COUNT(*) FROM core_schedule").fetchone()[0], 557)
            self.assertLessEqual(len(list(config.DB_PATH.parent.glob("pre_rebuild_*.db"))), 3)

    def test_network_is_disabled_during_rebuild(self):
        with TempEnv():
            http.NETWORK_ENABLED = False
            with self.assertRaises(http.NetworkDisabled):
                http.get("https://example.com")

    def test_failed_rebuild_keeps_live_db(self):
        with TempEnv():
            seed_schedule_raw()
            rebuild.run()
            live = db.content_hash(db.connect())
            seed_schedule_raw("game_id,season\n2025_01_X_Y,2025\n")  # newer, broken raw
            self.assertEqual(rebuild.run(), 1)
            self.assertEqual(db.content_hash(db.connect()), live)
