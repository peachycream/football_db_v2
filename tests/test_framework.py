import csv
import io
import unittest
from datetime import datetime, timezone

from fdb import db, loader as fw, registry, schedule
from fdb.loader import Loader, LoadRefused, Scope
from fdb.loaders.nflverse_schedules import ScheduleLoader
from tests.helpers import FIXTURES, TempEnv, seed_schedule_raw

UTC = timezone.utc


def loaded(env):
    c = env.conn()
    seed_schedule_raw()
    ld = ScheduleLoader()
    for sc in fw.scopes(c, ld):
        res = fw.load(c, ld, sc, apply=True)
        assert not res["failures"], res
    return c


class Completeness(unittest.TestCase):
    def test_2026_weeks_1_2_complete_week_3_not(self):
        with TempEnv() as env:
            c = loaded(env)
            now = datetime(2026, 9, 26, 17, 0, tzinfo=UTC)
            self.assertEqual(schedule.completed_weeks(c, 2026, now), [("REG", 1), ("REG", 2)])
            self.assertFalse(schedule.season_is_closed(c, 2026, now))
            self.assertTrue(schedule.season_is_closed(c, 2025, now))

    def test_settle_window(self):
        """Week 2's last game kicked off Mon 2026-09-21 20:15 ET = 2026-09-22 00:15Z.
        Final = kickoff + 4h game + 24h settle = 2026-09-23 04:15Z."""
        with TempEnv() as env:
            c = loaded(env)
            before = datetime(2026, 9, 23, 4, 14, tzinfo=UTC)
            after = datetime(2026, 9, 23, 4, 15, tzinfo=UTC)
            self.assertNotIn(("REG", 2), schedule.completed_weeks(c, 2026, before))
            self.assertIn(("REG", 2), schedule.completed_weeks(c, 2026, after))

    def test_missing_result_holds_week_open_forever(self):
        with TempEnv() as env:
            c = loaded(env)
            c.execute("UPDATE core_schedule SET result = NULL WHERE season = 2026 AND week = 1 AND rowid = "
                      "(SELECT MIN(rowid) FROM core_schedule WHERE season = 2026 AND week = 1)")
            far = datetime(2030, 1, 1, tzinfo=UTC)
            self.assertNotIn(("REG", 1), schedule.completed_weeks(c, 2026, far))


class WeekLoader(ScheduleLoader):
    """A week-grain loader, to prove the framework refuses incomplete weeks."""
    id, grain = "nflverse.schedules", "week"


class ScopeIsNotTheLoadersChoice(unittest.TestCase):
    def test_partial_week_refused(self):
        with TempEnv() as env:
            c = loaded(env)
            with self.assertRaises(LoadRefused):
                fw.load(c, WeekLoader(), Scope(2026, "REG", 3), apply=True)  # 1 of 16 played

    def test_week_scopes_come_from_schedule(self):
        import os
        with TempEnv() as env:
            c = loaded(env)
            os.environ["FDB_NOW"] = "2026-09-26T17:00:00Z"
            try:
                got = [s.label for s in fw.scopes(c, WeekLoader(), [2026])]
            finally:
                del os.environ["FDB_NOW"]
            self.assertEqual(got, ["season=2026/REG/week=1", "season=2026/REG/week=2"])


class Contract(unittest.TestCase):
    def test_missing_field_fails(self):
        with TempEnv() as env:
            c = env.conn()
            text = (FIXTURES / "games_2025_2026.csv").read_text()
            rows = list(csv.DictReader(io.StringIO(text)))
            out = io.StringIO()
            fields = [f for f in rows[0] if f != "home_score"]
            w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
            seed_schedule_raw(out.getvalue())
            res = fw.load(c, ScheduleLoader(), Scope(2025), apply=True)
            self.assertTrue(res["failures"] and "home_score" in res["failures"][0])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM core_schedule").fetchone()[0], 0)

    def test_failed_check_rolls_back(self):
        """Drop one 2025 game from the source: the check fails and the season's
        previous rows survive untouched."""
        with TempEnv() as env:
            c = loaded(env)
            before = db.table_hash(c, "core_schedule")
            text = (FIXTURES / "games_2025_2026.csv").read_text().splitlines()
            gone = next(i for i, l in enumerate(text) if l.startswith("2025_05_"))
            seed_schedule_raw("\n".join(text[:gone] + text[gone + 1:]) + "\n")
            res = fw.load(c, ScheduleLoader(), Scope(2025), apply=True)
            self.assertFalse(res["applied"])
            self.assertTrue(any("REG games" in f for f in res["failures"]))
            self.assertEqual(db.table_hash(c, "core_schedule"), before)

    def test_non_integer_is_not_truncated(self):
        with self.assertRaises(ValueError):
            fw._cast("1.5", "INTEGER")
        self.assertEqual(fw._cast("7.0", "INTEGER"), 7)
        self.assertIsNone(fw._cast("NA", "INTEGER"))

    def test_idempotent(self):
        with TempEnv() as env:
            c = loaded(env)
            ok, before, after = fw.check_idempotent(c, ScheduleLoader(), Scope(2026))
            self.assertTrue(ok, (before, after))


class Ownership(unittest.TestCase):
    def test_loader_cannot_write_unowned_table(self):
        class Intruder(ScheduleLoader):
            id = "someone.else"
        with TempEnv() as env:
            c = env.conn()
            seed_schedule_raw()
            with self.assertRaises(registry.OwnershipError):
                fw.load(c, Intruder(), Scope(2025))
