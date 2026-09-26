import unittest
from unittest import mock

from fdb.loaders.dp_playerids import DpPlayerIdsLoader
from fdb.loaders.nflverse_players import PlayersLoader

from fdb import config, db, http, rebuild
from tests.helpers import TempEnv, seed_identity_raw, seed_schedule_raw


SMALL = [mock.patch.object(PlayersLoader, "MIN_ROWS", 10), mock.patch.object(DpPlayerIdsLoader, "MIN_ROWS", 10)]


class Rebuild(unittest.TestCase):
    def setUp(self):
        for p in SMALL:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_truncated_players_file_refused(self):
        mock.patch.stopall()  # real minimum: the 25-row fixture must be refused as truncated
        with TempEnv():
            seed_schedule_raw()
            seed_identity_raw()
            self.assertEqual(rebuild.run(), 1)

    def test_rebuild_twice_identical_and_offline(self):
        with TempEnv():
            seed_schedule_raw()
            seed_identity_raw()
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
            seed_identity_raw()
            rebuild.run()
            live = db.content_hash(db.connect())
            seed_schedule_raw("game_id,season\n2025_01_X_Y,2025\n")  # newer, broken raw
            self.assertEqual(rebuild.run(), 1)
            self.assertEqual(db.content_hash(db.connect()), live)
