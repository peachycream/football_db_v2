"""Phase 5: FTN client paging traps, personnel vocabularies, the seam mart. Offline."""
import json
import unittest
import urllib.error
from unittest import mock

from fdb import ftn
from fdb.participation import ftn_counts, nflverse_counts, personnel


class Paging(unittest.TestCase):
    def pages(self, sizes, end="empty"):
        """Mocked /plays: pages of the given sizes, then [] or a 404 'Season not found'."""
        calls = []

        def fake(url, headers=None, timeout=None):
            calls.append(url)
            i = len(calls) - 1
            if i < len(sizes):
                return 200, {}, json.dumps([{"pid": i * 10000 + k} for k in range(sizes[i])]).encode()
            if end == "404":
                raise urllib.error.HTTPError(url, 404, "nf", {}, __import__("io").BytesIO(b'"Season not found"'))
            return 200, {}, b"[]"
        return fake, calls

    def run_pages(self, sizes, end="empty"):
        fake, calls = self.pages(sizes, end)
        with mock.patch.object(ftn.http, "request", side_effect=fake), mock.patch.object(ftn.config, "env", return_value="k"), \
                mock.patch.object(ftn, "MIN_INTERVAL", 0):
            body, params = ftn.get_pages("/games/2025/plays")
        return ftn.flatten(body), calls

    def test_page_cap_below_count_does_not_truncate(self):
        """/plays caps pages at 1000 though count=2000: must keep going (v2 first pull got 1000 plays/season)."""
        rows, calls = self.run_pages([1000, 1000, 323])
        self.assertEqual(len(rows), 2323)
        self.assertEqual(len(calls), 3)   # the short page ends it

    def test_exact_multiple_ends_on_404(self):
        rows, _ = self.run_pages([1000, 1000], end="404")
        self.assertEqual(len(rows), 2000)

    def test_404_on_first_page_is_an_error(self):
        fake, _ = self.pages([], end="404")
        with mock.patch.object(ftn.http, "request", side_effect=fake), mock.patch.object(ftn.config, "env", return_value="k"), \
                mock.patch.object(ftn, "MIN_INTERVAL", 0):
            with self.assertRaises(ftn.FtnError):
                ftn.get_pages("/games/2030/plays")


class Vocabulary(unittest.TestCase):
    def test_nflverse_both_eras(self):
        self.assertEqual(personnel(nflverse_counts("1 RB, 1 TE, 3 WR")), "11")
        self.assertEqual(personnel(nflverse_counts("1 C, 1 FB, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 2 WR")), "21")  # FB is a back
        self.assertIsNone(nflverse_counts("1 RB, 1 TE, 2 WR"))   # 4 skill players: unknown, not guessed
        self.assertIsNone(nflverse_counts(None))

    def test_ftn_personnel_is_by_roster_position_not_alignment(self):
        # FTN would code a split-out TE 'SLT'; the roster position says TE -> 12, not 11.
        self.assertEqual(personnel(ftn_counts(["RB", "TE", "TE", "WR", "WR"])), "12")
        self.assertEqual(personnel(ftn_counts(["RB", "FB", "TE", "WR", "WR"])), "21")
        self.assertIsNone(ftn_counts(["RB", "TE", "WR", "WR", "T"]))   # a lineman reporting eligible: unknown
        self.assertIsNone(ftn_counts(["RB", "TE", "WR", "WR", None]))  # an id with no roster position


class CancelledGame(unittest.TestCase):
    def test_ftn_games_check_uses_the_schedule_exception(self):
        from fdb.loaders.nflverse_schedules import CANCELLED_REG
        self.assertEqual(CANCELLED_REG[2022], {"BUF", "CIN"})  # FTN gid 6134, 2022 wk17, never played
