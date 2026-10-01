"""FTN Fantasy team DVOA: client and loader. Offline. Source facts: fdb/ftnfantasy.py (verified live 2026-10-01)."""
import json
import os
import unittest
import urllib.error
from unittest import mock

from fdb import ftnfantasy as api, loader as fw, raw
from fdb.loaders import get
from fdb.loaders.nflverse_schedules import ScheduleLoader
from tests.helpers import TempEnv, seed_schedule_raw

NOW = "2026-09-26T17:00:00Z"
# FTN spells some teams its own way; team_aliases maps them (BLT -> BAL ...).
FTN_CODE = {"ARI": "ARZ", "BAL": "BLT", "CLE": "CLV", "HOU": "HST"}


def row(team, off=0.1, dfn=-0.1, **kw):
    r = {"team": FTN_CODE.get(team, team), "id": 1, "games": 1, "wins": 1, "losses": 0, "ties": 0, "offDvoa": off, "defDvoa": dfn,
         "totalDvoa": off - dfn, "offVoaUnadj": 0, "defVoaUnadj": dfn, "offenseBaseline": 50.0, "defenseBaseline": 50.0}
    r.update(kw)
    return r


class Env(TempEnv):
    def __enter__(self):
        super().__enter__()
        self.p = mock.patch.dict(os.environ, {"FDB_NOW": NOW, "FTN_USER": "me@example.com", "FTN_PASS": "pw-secret"})
        self.p.start()
        self.c = self.conn()
        seed_schedule_raw()
        ld = ScheduleLoader()
        for sc in fw.scopes(self.c, ld):
            assert not fw.load(self.c, ld, sc, apply=True)["failures"]
        api._state.update(token=None, last=0.0)
        return self

    def __exit__(self, *exc):
        self.p.stop()
        return super().__exit__(*exc)

    def teams(self, season, week):
        return sorted({t for r in self.c.execute("SELECT home_team, away_team FROM core_schedule WHERE season = ? AND season_type = 'REG' AND week = ?",
                                                  (season, week)) for t in r})

    def week_rows(self, season, week, **kw):
        # alternate +x / -x so the week sums to zero, as DVOA does
        return [row(t, off=(0.2 if i % 2 else -0.2), dfn=(-0.1 if i % 2 else 0.1), **kw) for i, t in enumerate(self.teams(season, week))]

    def seed(self, season, week, rows):
        return raw.write("ftnfantasy", "statshub_dvoa_team", f"{season}/REG{week:02d}", json.dumps(rows).encode(), "json", {}, len(rows), False)


class Client(unittest.TestCase):
    def test_logs_in_once_and_sends_the_bearer_and_records_no_secret(self):
        calls = []

        def fake(url, data=None, headers=None, timeout=60):
            calls.append((url, headers, json.loads(data)))
            if url == api.LOGIN:
                return 200, {}, json.dumps({"status": "success", "user_id": "9", "access_token": "tok1", "refresh_token": "r"}).encode()
            return 200, {}, b'[{"team": "GB"}]'
        with Env():
            with mock.patch.object(api.http, "request", side_effect=fake), mock.patch.object(api, "MIN_GAP_S", 0):
                body, params = api.dvoa_team(2025, 1)
                api.dvoa_team(2025, 2)
        self.assertEqual(body, b'[{"team": "GB"}]')
        self.assertEqual(sum(u == api.LOGIN for u, _, _ in calls), 1)
        url, headers, sent = calls[1]
        self.assertTrue(url.endswith("/dvoa/team"))
        self.assertEqual(headers["Authorization"], "Bearer tok1")
        self.assertEqual((sent["year"], sent["weeks"], sent["seasonType"], sent["teams"], sent["downs"]), (2025, [1], "reg", [], []))
        blob = json.dumps(params)
        for secret in ("pw-secret", "tok1", "me@example.com"):
            self.assertNotIn(secret, blob)

    def test_rejected_token_relogs_once(self):
        state = {"n": 0}

        def fake(url, data=None, headers=None, timeout=60):
            if url == api.LOGIN:
                state["n"] += 1
                return 200, {}, json.dumps({"status": "success", "access_token": f"tok{state['n']}"}).encode()
            if headers["Authorization"] == "Bearer tok1":
                raise urllib.error.HTTPError(url, 401, "no", {}, None)
            return 200, {}, b"[]"
        with Env():
            with mock.patch.object(api.http, "request", side_effect=fake), mock.patch.object(api, "MIN_GAP_S", 0):
                body, _ = api.dvoa_team(2018, 1)
        self.assertEqual((body, state["n"]), (b"[]", 2))

    def test_refused_login_names_the_code_and_not_the_account(self):
        def fake(url, data=None, headers=None, timeout=60):
            raise urllib.error.HTTPError(url, 401, "no", {}, None)
        with Env():
            with mock.patch.object(api.http, "request", side_effect=fake):
                with self.assertRaises(api.FtnFantasyError) as cm:
                    api.login()
        self.assertIn("HTTP 401", str(cm.exception))
        self.assertNotIn("me@example.com", str(cm.exception))

    def test_missing_setting_names_the_variable(self):
        with Env():
            with mock.patch.dict(os.environ, {"FTN_USER": ""}), mock.patch.object(api.config, "env", side_effect=lambda n, d="": os.environ.get(n, d)):
                with self.assertRaises(api.FtnFantasyError) as cm:
                    api.login()
        self.assertIn("FTN_USER", str(cm.exception))

    def test_a_non_list_answer_is_refused(self):
        def fake(url, data=None, headers=None, timeout=60):
            return (200, {}, b'{"status": "success", "access_token": "t"}') if url == api.LOGIN else (200, {}, b'{"message": "x"}')
        with Env():
            with mock.patch.object(api.http, "request", side_effect=fake), mock.patch.object(api, "MIN_GAP_S", 0):
                with self.assertRaises(api.FtnFantasyError):
                    api.dvoa_team(2025, 1)


class Loader(unittest.TestCase):
    def test_scopes_are_reg_weeks_from_2018_completed_only(self):
        with Env() as env:
            sc = fw.scopes(env.c, get("ftnfantasy.dvoa_team"))
            self.assertTrue(sc)
            self.assertEqual({s.season_type for s in sc}, {"REG"})
            self.assertEqual([s.week for s in sc if s.season == 2026], [1, 2])

    def test_documented_source_gap_is_never_offered_or_fetched(self):
        from fdb.loaders.ftnfantasy import SOURCE_DEFECTS
        self.assertEqual(sorted(SOURCE_DEFECTS), [(2022, "REG", 5)])
        with Env() as env:
            ld = get("ftnfantasy.dvoa_team")
            with mock.patch.object(type(ld), "unavailable", {(2025, "REG", 3): "gap"}):   # the fixture schedule is 2025-2026
                weeks = {(s.season, s.week) for s in fw.scopes(env.c, ld)}
                parts = set(fw.fetch_partitions(env.c, ld))
            self.assertNotIn((2025, 3), weeks)
            self.assertNotIn("2025/REG03", parts)
            self.assertTrue({(2025, 2), (2025, 4)} <= weeks)

    def test_an_empty_answer_is_never_loaded(self):
        with Env() as env:
            env.seed(2026, 1, [])
            res = fw.load(env.c, get("ftnfantasy.dvoa_team"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(res["failures"])
            self.assertFalse(res["applied"])
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM core_ftn_dvoa_team_week").fetchone()[0], 0)

    def test_fetch_asks_for_exactly_that_week(self):
        with Env():
            with mock.patch.object(api, "dvoa_team", return_value=(b"[]", {})) as r:
                get("ftnfantasy.dvoa_team").fetch("2025/REG07")
            self.assertEqual(r.call_args.args, (2025, 7))

    def test_full_week_loads_with_source_names_and_is_idempotent(self):
        with Env() as env:
            rows = env.week_rows(2026, 1)
            env.seed(2026, 1, rows)
            ld = get("ftnfantasy.dvoa_team")
            res = fw.load(env.c, ld, fw.Scope(2026, "REG", 1), apply=True)
            self.assertEqual((res["failures"], res["rows"]), ([], len(rows)))
            r = env.c.execute("SELECT * FROM core_ftn_dvoa_team_week WHERE season = 2026 AND week = 1 LIMIT 1").fetchone()
            self.assertEqual(r["season_type"], "REG")
            self.assertIsNotNone(r["offDvoa"])           # source name, camelCase, kept verbatim
            ok, before, after = fw.check_idempotent(env.c, ld, fw.Scope(2026, "REG", 1))
            self.assertTrue(ok, (before, after))

    def test_mart_renames_once_and_resolves_ftn_spellings_to_the_franchise(self):
        with Env() as env:
            env.seed(2026, 1, env.week_rows(2026, 1))
            fw.load(env.c, get("ftnfantasy.dvoa_team"), fw.Scope(2026, "REG", 1), apply=True)
            teams = {r[0] for r in env.c.execute("SELECT team FROM mart_team_dvoa_week WHERE season = 2026 AND week = 1")}
            self.assertEqual(teams, set(env.teams(2026, 1)))      # BLT/ARZ/CLV/HST came back as BAL/ARI/CLE/HOU
            cols = [d[0] for d in env.c.execute("SELECT * FROM mart_team_dvoa_week").description]
            self.assertTrue({"off_dvoa", "def_dvoa", "total_dvoa"} <= set(cols))
            self.assertNotIn("offDvoa", cols)

    def test_partial_week_is_refused(self):
        with Env() as env:
            drop = env.teams(2026, 1)[:2]
            env.seed(2026, 1, [r for r in env.week_rows(2026, 1) if r["team"] not in {FTN_CODE.get(t, t) for t in drop}])
            res = fw.load(env.c, get("ftnfantasy.dvoa_team"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("scheduled teams missing" in f for f in res["failures"]), res["failures"])
            self.assertFalse(res["applied"])

    def test_odd_data_is_refused(self):
        cases = (({"games": 2}, "games != 1"), ({"offDvoa": None}, "NULL"), ({"offDvoa": 4.0, "totalDvoa": 4.1}, "|DVOA| >"))
        for kw, expect in cases:
            with Env() as env:
                env.seed(2026, 1, env.week_rows(2026, 1, **kw))
                res = fw.load(env.c, get("ftnfantasy.dvoa_team"), fw.Scope(2026, "REG", 1), apply=True)
                self.assertTrue(any(expect in f for f in res["failures"]), (expect, res["failures"]))
                self.assertFalse(res["applied"])

    def test_a_week_that_does_not_sum_to_about_zero_is_refused(self):
        with Env() as env:
            env.seed(2026, 1, [row(t, off=0.9, dfn=0.0) for t in env.teams(2026, 1)])
            res = fw.load(env.c, get("ftnfantasy.dvoa_team"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("far from the league" in f for f in res["failures"]), res["failures"])

    def test_missing_source_field_fails_the_load(self):
        with Env() as env:
            env.seed(2026, 1, [{k: v for k, v in r.items() if k != "defDvoa"} for r in env.week_rows(2026, 1)])
            res = fw.load(env.c, get("ftnfantasy.dvoa_team"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("defDvoa" in f for f in res["failures"]), res["failures"])

    def test_in_season_raw_is_never_final_but_a_closed_season_is(self):
        with Env() as env:
            ld = get("ftnfantasy.dvoa_team")
            self.assertFalse(ld.raw_is_final(env.c, "2026/REG01"))
            self.assertTrue(ld.raw_is_final(env.c, "2025/REG01"))

    def test_owner_is_enforced(self):
        from fdb.registry import OwnershipError
        with Env() as env:
            ld = get("ftnfantasy.dvoa_team")
            with mock.patch.object(type(ld), "table", "core_ftn_games"):
                with self.assertRaises(OwnershipError):
                    fw.load(env.c, ld, fw.Scope(2026, "REG", 1), apply=True)


class AppDvoa(unittest.TestCase):
    """app/env.py: play-weighted window DVOA (rule 4), per-week trend, orientation, gaps. In-memory marts."""

    def setUp(self):
        import sqlite3
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE mart_team_dvoa_week (season, season_type, week, team, off_dvoa, def_dvoa);
            CREATE TABLE mart_team_off_env_week (season, season_type, week, team, split, plays);
            CREATE TABLE mart_team_def_env_week (season, season_type, week, team, def_plays);""")
        # AAA: weeks 1-2 with very different play counts. BBB: one game. Week 3 for AAA has DVOA but no plays row (a gap).
        for wk, team, off, dfn, plays in ((1, "AAA", 0.50, -0.20, 90), (2, "AAA", 0.00, 0.10, 10), (1, "BBB", -0.10, 0.30, 60)):
            self.con.execute("INSERT INTO mart_team_dvoa_week VALUES (2026,'REG',?,?,?,?)", (wk, team, off, dfn))
            self.con.execute("INSERT INTO mart_team_off_env_week VALUES (2026,'REG',?,?,'all',?)", (wk, team, plays))
            self.con.execute("INSERT INTO mart_team_off_env_week VALUES (2026,'REG',?,?,'pass',?)", (wk, team, 5))
            self.con.execute("INSERT INTO mart_team_def_env_week VALUES (2026,'REG',?,?,?)", (wk, team, plays))
        self.con.execute("INSERT INTO mart_team_dvoa_week VALUES (2026,'REG',3,'AAA',0.9,0.9)")

    def test_window_is_play_weighted_not_a_mean_of_weekly_rates(self):
        from app import env
        tile, trend, median, by_team = env._dvoa_block(self.con, 2026, 1, 3, "AAA", "off")
        self.assertAlmostEqual(by_team["AAA"], (0.50 * 90 + 0.00 * 10) / 100)       # 0.45, not the plain mean 0.25
        self.assertAlmostEqual(tile["v"], 0.45, places=6)

    def test_week_without_plays_carries_no_weight_and_no_trend_point(self):
        from app import env
        _, trend, _, by_team = env._dvoa_block(self.con, 2026, 1, 3, "AAA", "off")
        self.assertEqual([w for w, _ in trend], [1, 2])                              # week 3 has DVOA but no plays row
        self.assertAlmostEqual(by_team["AAA"], 0.45)

    def test_single_week_equals_the_source_value_and_median_is_per_week(self):
        from app import env
        tile, trend, median, _ = env._dvoa_block(self.con, 2026, 1, 1, "AAA", "off")
        self.assertEqual((tile["v"], trend), (0.5, [[1, 0.5]]))
        self.assertEqual(median, [[1, 0.2]])                                         # median of (0.5, -0.1)

    def test_defense_uses_def_dvoa_weighted_by_plays_faced_and_lower_is_better(self):
        from app import env
        tile, _, _, by_team = env._dvoa_block(self.con, 2026, 1, 1, "AAA", "def")
        self.assertAlmostEqual(by_team["AAA"], -0.20)
        self.assertEqual(tile["rank"], 1)                                            # -0.20 beats BBB's +0.30

    def test_offense_higher_is_better_and_a_missing_team_is_none(self):
        from app import env
        tile, trend, _, _ = env._dvoa_block(self.con, 2026, 1, 1, "AAA", "off")
        self.assertEqual(tile["rank"], 1)
        tile, trend, _, _ = env._dvoa_block(self.con, 2026, 1, 1, "ZZZ", "off")
        self.assertEqual((tile["v"], tile["pct"], trend), (None, None, []))


if __name__ == "__main__":
    unittest.main()
