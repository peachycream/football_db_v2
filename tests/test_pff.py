"""Phase 4: PFF client guards, week vocabulary, weekly + season loaders. Offline."""
import json
import os
import unittest
from unittest import mock

from fdb import loader as fw, pff, raw
from fdb.loaders import get
from fdb.loaders.nflverse_schedules import ScheduleLoader
from fdb.loaders.pff import post_week_map
from tests.helpers import TempEnv, seed_schedule_raw

NOW = "2026-09-26T17:00:00Z"


def defense_rows(teams, snaps=660):
    """One defender per team, every contracted field present (0 unless it matters):
    enough for the team-coverage and plausibility checks."""
    fields = get("pff.defense_week").expected_fields()
    out = []
    for i, t in enumerate(teams):
        row = {f: 0 for f in fields}
        row.update({"player_id": 1000 + i, "player": f"P {i}", "position": "LB", "team_name": t, "team": t,
                    "franchise_id": i + 1, "jersey_number": "1", "player_game_count": 1, "snap_counts_defense": snaps})
        out.append(row)
    return {"defense_summary": out}


class Env(TempEnv):
    def __enter__(self):
        super().__enter__()
        self.p = mock.patch.dict(os.environ, {"FDB_NOW": NOW})
        self.p.start()
        self.c = self.conn()
        seed_schedule_raw()
        ld = ScheduleLoader()
        for sc in fw.scopes(self.c, ld):
            assert not fw.load(self.c, ld, sc, apply=True)["failures"]
        return self

    def __exit__(self, *exc):
        self.p.stop()
        return super().__exit__(*exc)

    def teams(self, season, st, week):
        return sorted({t for r in self.c.execute("""SELECT home_team, away_team FROM core_schedule
                        WHERE season = ? AND season_type = ? AND week = ?""", (season, st, week)) for t in r})


class Client(unittest.TestCase):
    def test_restricted_columns_raise(self):
        body = json.dumps({"defense_summary": [], "restricted_columns": ["grades_defense"]}).encode()
        with mock.patch.object(pff.http, "request", return_value=(200, {}, body)), \
                mock.patch.object(pff, "_key", return_value="k"):
            with self.assertRaises(pff.PffError):
                pff.get("/v1/facet/defense/summary", league="nfl", season=2025, week=1)

    def test_error_payload_raises(self):
        body = json.dumps({"error": {"code": "bad_request", "message": "x"}}).encode()
        with mock.patch.object(pff.http, "request", return_value=(200, {}, body)), \
                mock.patch.object(pff, "_key", return_value="k"):
            with self.assertRaises(pff.PffError):
                pff.get("/v1/facet/defense/summary", league="nfl", season=2025)

    def test_rows_of_needs_exactly_one_list(self):
        self.assertEqual(pff.rows_of({"defense_summary": [{"a": 1}]}), ("defense_summary", [{"a": 1}]))
        with self.assertRaises(ValueError):  # receiving/coverage nests three lists; reading one would lie
            pff.rows_of({"defenders": [], "receivers": []})


class WeekVocabulary(unittest.TestCase):
    def test_post_weeks_map_in_order_to_28_29_30_32(self):
        with Env() as env:
            self.assertEqual(post_week_map(env.c, 2025), {19: 28, 20: 29, 21: 30, 22: 32})

    def test_partition_round_trip(self):
        ld = get("pff.defense_week")
        for sc in (fw.Scope(2025, "REG", 7), fw.Scope(2025, "POST", 19)):
            self.assertEqual(ld._split(ld.partition(sc)), (sc.season, sc.season_type, sc.week))

    def test_fetch_requests_pff_week_numbers(self):
        with Env() as env:
            ld = get("pff.defense_week")
            ld.prepare(env.c)
            with mock.patch.object(pff, "get", return_value=(b"{}", {})) as g:
                ld.fetch("2025/POST22")
            self.assertEqual(g.call_args.kwargs["week"], 32)   # the Super Bowl, never 31 (Pro Bowl)


class WeeklyLoader(unittest.TestCase):
    def seed(self, env, obj, part="2026/REG01"):
        payload = json.dumps(obj).encode()
        return raw.write("pff", "defense_summary", part, payload, "json", {}, 1, False)

    def test_full_week_loads_with_both_week_numbers(self):
        with Env() as env:
            self.seed(env, defense_rows(env.teams(2026, "REG", 1)))
            res = fw.load(env.c, get("pff.defense_week"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertEqual(res["failures"], [])
            self.assertEqual([tuple(r) for r in env.c.execute("SELECT DISTINCT week, pff_week FROM core_pff_defense_week")], [(1, 1)])

    def test_partial_week_is_refused(self):
        with Env() as env:
            self.seed(env, defense_rows(env.teams(2026, "REG", 1)[:-2]))  # two scheduled teams missing
            res = fw.load(env.c, get("pff.defense_week"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("scheduled teams missing" in f for f in res["failures"]), res["failures"])

    def test_implausible_team_snaps_refused(self):
        with Env() as env:
            self.seed(env, defense_rows(env.teams(2026, "REG", 1), snaps=40))  # 40/11 = 3.6 plays
            res = fw.load(env.c, get("pff.defense_week"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("implausible defensive plays" in f for f in res["failures"]), res["failures"])

    def test_empty_week_never_loaded_or_final(self):
        with Env() as env:
            self.seed(env, {"defense_summary": []})
            res = fw.load(env.c, get("pff.defense_week"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertFalse(res["applied"])   # refused (the field contract fires before the emptiness rule)
            self.assertTrue(res["failures"])

    def test_week_not_complete_is_refused(self):
        with Env() as env:
            self.seed(env, defense_rows(env.teams(2026, "REG", 3)), part="2026/REG03")
            with self.assertRaises(fw.LoadRefused):
                fw.load(env.c, get("pff.defense_week"), fw.Scope(2026, "REG", 3), apply=True)


class SeasonLoader(unittest.TestCase):
    def test_week_list_is_completed_weeks_in_pff_numbers(self):
        with Env() as env:
            ld = get("pff.defense_season")
            ld.prepare(env.c)
            self.assertEqual(ld._weeks(2026), "1,2")
            self.assertTrue(ld._weeks(2025).endswith(",18,28,29,30,32"))

    def test_game_count_beyond_weeks_requested_fails(self):
        """A player with more games than weeks requested = preseason leaked in."""
        with Env() as env:
            rows = [dict(r, player_game_count=5) for r in defense_rows(["KC"])["defense_summary"]]
            payload = json.dumps({"defense_summary": rows}).encode()
            raw.write("pff", "defense_summary_season", "2026", payload, "json", {"week": "1,2"}, 1, False)
            ld = get("pff.defense_season")
            with mock.patch.object(ld.__class__, "MIN_ROWS", 1):
                res = fw.load(env.c, ld, fw.Scope(2026), apply=True)
            self.assertTrue(any("preseason leaked" in f for f in res["failures"]), res["failures"])
