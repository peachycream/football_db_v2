import unittest

from fdb import loader as fw, raw
from fdb.loader import Loader, Scope
from tests.helpers import TempEnv


class NestedEmpty(unittest.TestCase):
    def test_nested_empty_is_empty(self):
        for obj in ({"x": []}, {"coverage_scheme": []}, {"a": {"b": []}}, [], [[]], None, "", " ", {}):
            self.assertTrue(raw.is_effectively_empty(obj), obj)

    def test_values_are_not_empty(self):
        for obj in ({"x": [0]}, [{"a": 1}], 0, False, {"a": "x"}, [[], [1]]):
            self.assertFalse(raw.is_effectively_empty(obj), obj)


class FakeLoader(Loader):
    id, source, endpoint, table, grain, ext = "fake.feed", "fake", "feed", "core_schedule", "reference", "json"

    def __init__(self, payload=b'[{"a": 1}]', final=False):
        self.payload, self.final, self.calls = payload, final, 0

    def partition(self, scope): return "all"
    def fetch(self, partition):
        self.calls += 1
        return self.payload, {}
    def parse(self, payload):
        import json
        rows = json.loads(payload)
        return (sorted(rows[0]) if rows and isinstance(rows, list) and isinstance(rows[0], dict) else []), rows
    def raw_is_final(self, conn, partition): return self.final


class CachePolicy(unittest.TestCase):
    def test_non_final_is_refetched(self):
        with TempEnv() as env:
            c, ld = env.conn(), FakeLoader(final=False)
            fw.fetch(c, ld, "all"); fw.fetch(c, ld, "all")
            self.assertEqual(ld.calls, 2)

    def test_final_is_served_from_cache(self):
        with TempEnv() as env:
            c, ld = env.conn(), FakeLoader(final=True)
            _, first = fw.fetch(c, ld, "all")
            _, second = fw.fetch(c, ld, "all")
            self.assertEqual((ld.calls, first, second), (1, True, False))

    def test_empty_is_never_final_or_served(self):
        with TempEnv() as env:
            c, ld = env.conn(), FakeLoader(payload=b'[{"coverage_scheme": []}]', final=True)
            ld.parse = lambda p: ([], [{"coverage_scheme": []}])
            rec, _ = fw.fetch(c, ld, "all")
            self.assertFalse(rec.is_final)
            fw.fetch(c, ld, "all")
            self.assertEqual(ld.calls, 2)

    def test_refetch_flag_bypasses_cache(self):
        with TempEnv() as env:
            c, ld = env.conn(), FakeLoader(final=True)
            fw.fetch(c, ld, "all"); fw.fetch(c, ld, "all", refetch=True)
            self.assertEqual(ld.calls, 2)

    def test_raw_is_immutable_and_indexed(self):
        with TempEnv() as env:
            c, ld = env.conn(), FakeLoader()
            fw.fetch(c, ld, "all"); fw.fetch(c, ld, "all")
            self.assertEqual(len(raw.records("fake", "feed", "all")), 2)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM raw_fetch_log").fetchone()[0], 2)


class Retention(unittest.TestCase):
    def test_keeps_newest_three_non_final_and_every_final(self):
        with TempEnv():
            for i in range(5):
                raw.write("fake", "feed", "all", b"x", "txt", {}, 1, is_final=(i == 0))
            recs = raw.records("fake", "feed", "all")
            self.assertEqual(sum(r.is_final for r in recs), 1)       # the final one survives
            self.assertEqual(sum(not r.is_final for r in recs), 3)   # newest 3 non-final
