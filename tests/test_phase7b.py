"""Phase 7b: expected tackles/sacks model pieces and the pass-rush erratum rule. Offline."""
import unittest

from fdb import idp_model as m
from fdb.loaders import pff as pff_loaders


def play(**kw):
    base = dict(sack=0, rush_attempt=0, complete_pass=0, run_location=None, run_gap=None, pass_location=None, yards_gained=0)
    return {**base, **kw}


class Cells(unittest.TestCase):
    def test_kinds_gaps_depths(self):
        self.assertEqual(m.cell_of(play(sack=1, yards_gained=-7)), ("sack", "none", "none"))
        self.assertEqual(m.cell_of(play(rush_attempt=1, run_location="middle", run_gap=None, yards_gained=3)), ("run", "middle", "1-3"))
        self.assertEqual(m.cell_of(play(rush_attempt=1, run_location="left", run_gap="end", yards_gained=-2)), ("run", "end", "<=0"))
        self.assertEqual(m.cell_of(play(complete_pass=1, pass_location="right", yards_gained=25)), ("complete", "outside", "21+"))
        self.assertEqual(m.cell_of(play(complete_pass=1, pass_location="middle", yards_gained=11)), ("complete", "middle", "11-20"))
        self.assertEqual(m.cell_of(play(yards_gained=0)), ("incomplete", "none", "none"))

    def test_depth_bucket_edges(self):
        self.assertEqual([m._depth(y) for y in (0, 1, 3, 4, 6, 7, 10, 11, 20, 21)],
                         ["<=0", "1-3", "1-3", "4-6", "4-6", "7-10", "7-10", "11-20", "11-20", "21+"])


class Rates(unittest.TestCase):
    def test_thin_cell_shrinks_to_its_parent(self):
        counts = {("LB", "run", "end", "1-3"): [10, 10],          # 100% on 10 plays: must not stand
                  ("LB", "run", "guard", "1-3"): [10000, 1000]}   # parent (LB, run, 1-3) ~ 0.1
        rates, parent, grand = m.fit_rates(counts)
        self.assertLess(rates[("LB", "run", "end", "1-3")], 0.2)
        self.assertAlmostEqual(rates[("LB", "run", "guard", "1-3")], 0.1, places=2)

    def test_big_cells_keep_their_own_rate(self):
        counts = {("S", "complete", "outside", "21+"): [50000, 15000], ("S", "complete", "middle", "21+"): [50000, 5000]}
        rates, _, _ = m.fit_rates(counts)
        self.assertAlmostEqual(rates[("S", "complete", "outside", "21+")], 0.3, places=2)
        self.assertAlmostEqual(rates[("S", "complete", "middle", "21+")], 0.1, places=2)

    def test_fit_window_excludes_the_validation_season(self):
        self.assertNotIn(2025, m.FIT_SEASONS)
        self.assertEqual((min(m.FIT_SEASONS), max(m.FIT_SEASONS)), (2016, 2024))


class Errata(unittest.TestCase):
    def test_named_pff_rows_are_keyed_exactly(self):
        for k in pff_loaders.PASS_RUSH_ERRATA:
            self.assertEqual(len(k), 4)
            self.assertIn(k[1], ("REG", "POST"))



class LaggedFeed(unittest.TestCase):
    """Phase 8: FTN all-22 publishes days after the games. All games 404 -> NotPublished
    (pending within grace); some games 404 -> a hard failure (never a partial week)."""

    def _fetch(self, found):
        from unittest import mock
        from fdb import ftn as api
        from fdb.loader import NotPublished
        from fdb.loaders.ftn import All22Loader
        from tests.helpers import TempEnv
        with TempEnv() as t:
            c = t.conn()
            c.execute("PRAGMA foreign_keys = OFF")
            c.executemany("INSERT INTO core_ftn_games (season, gid, week, load_id) VALUES (2026, ?, 3, 1)", [(1,), (2,)])
            ld = All22Loader()
            ld.prepare(c)

            def fake(path):
                gid = int(path.rsplit("/", 1)[1])
                if gid in found:
                    return b"[]", {}
                raise api.FtnError(f'HTTP 404 for {path}: "Game not found"')
            with mock.patch.object(api, "get", side_effect=fake):
                try:
                    return ld.fetch("2026/REG03")
                except NotPublished as e:
                    return e
                except api.FtnError as e:
                    return e
                finally:
                    c.close()

    def test_nothing_published_is_not_published(self):
        from fdb.loader import NotPublished
        self.assertIsInstance(self._fetch(found=set()), NotPublished)

    def test_partial_week_is_a_failure(self):
        from fdb.loader import NotPublished
        r = self._fetch(found={1})
        self.assertNotIsInstance(r, NotPublished)
        self.assertIn("partial all-22", str(r))

    def test_all_published_fetches(self):
        body, params = self._fetch(found={1, 2})
        self.assertEqual(body, b'{"1":[],"2":[]}')

    def test_grace_is_bounded(self):
        from fdb.loaders.ftn import All22Loader
        self.assertEqual(All22Loader.publish_grace_days, 14)
        from fdb.loader import Loader
        self.assertEqual(Loader.publish_grace_days, 0)   # every other loader: never pending


if __name__ == "__main__":
    unittest.main()
