import unittest

from fdb.timeutil import eastern_to_utc


class Eastern(unittest.TestCase):
    def test_edt(self):  # Monday night week 1 2026
        self.assertEqual(eastern_to_utc("2026-09-14", "20:15").isoformat(), "2026-09-15T00:15:00+00:00")

    def test_est(self):
        self.assertEqual(eastern_to_utc("2025-12-01", "13:00").isoformat(), "2025-12-01T18:00:00+00:00")

    def test_dst_ends_first_sunday_of_november(self):  # 2026-11-01 is that Sunday
        self.assertEqual(eastern_to_utc("2026-11-01", "13:00").isoformat(), "2026-11-01T18:00:00+00:00")
        self.assertEqual(eastern_to_utc("2026-10-31", "13:00").isoformat(), "2026-10-31T17:00:00+00:00")
