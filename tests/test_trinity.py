"""DD Fantasy Football Trinity: client, loaders, the ported score and the mart builder. Offline.

The port is proven three ways here and a fourth live (REBUILD_LOG.md, Phase 9): (1) a population
small enough to compute by hand, (2) JavaScript rounding semantics, (3) clamping and the filters.
"""
import json
import os
import unittest
import urllib.error
from unittest import mock

from fdb import ddff, db, loader as fw, raw, trinity
from fdb.loaders import get
from fdb.loaders.nflverse_schedules import ScheduleLoader
from tests.helpers import TempEnv, seed_schedule_raw

NOW = "2026-09-26T17:00:00Z"
FIELDS = ["player_gsis_id", "full_name", "pos", "sleeper_id", "team", "games", "routes", "targets", "rec", "rec_yards",
          "yac", "rec_td", "first_downs", "player_air_yards", "team_air_yards"]


def agg(i, pos="WR", team="KC", **kw):
    row = {"player_gsis_id": f"00-{i:07d}", "full_name": f"P {i}", "pos": pos, "sleeper_id": str(1000 + i), "team": team,
           "games": 1, "routes": 30, "targets": 6, "rec": 4, "rec_yards": 50, "yac": 10, "rec_td": 0, "first_downs": 3,
           "player_air_yards": 60, "team_air_yards": 240}
    row.update(kw)
    return row


class Port(unittest.TestCase):
    def test_javascript_rounding_rounds_halves_up(self):
        self.assertEqual([trinity.js_round(x) for x in (0.5, 1.5, 2.5, -0.5, -2.5, 2.4999)], [1, 2, 3, 0, -2, 2])

    def test_target_floor_scales_with_the_window(self):
        self.assertEqual([trinity.min_targets(g) for g in (1, 3, 9, 17, 0, None)], [1, 1, 3, 5, 5, 5])

    def test_two_player_pool_is_computed_by_hand(self):
        # n=2: z = +-(1/sqrt 2) on every metric; score = 5 +- (.36+.30+.34+.38+.29) * 0.7071068
        hi = agg(1, first_downs=6, rec_yards=90, yac=30, rec=8, player_air_yards=120)
        lo = agg(2, first_downs=1, rec_yards=20, yac=2, rec=1, player_air_yards=10)
        out = {o["row"]["sleeper_id"]: o for o in trinity.score_window([hi, lo], 1)}
        self.assertEqual(out["1001"]["trinity_score"], 6.18)
        self.assertEqual(out["1002"]["trinity_score"], 3.82)
        self.assertAlmostEqual(out["1001"]["z_yprr"], 0.70710678, places=6)

    def test_rb_is_scored_against_the_wr_te_pool_but_not_in_it(self):
        hi, lo = agg(1, first_downs=6, rec_yards=90, yac=30, rec=8, player_air_yards=120), agg(2, first_downs=1, rec_yards=20, yac=2, rec=1, player_air_yards=10)
        mid = agg(3, pos="RB", first_downs=3.5, rec_yards=55, yac=16, rec=4.5, player_air_yards=65)
        with_rb = {o["row"]["sleeper_id"]: o["trinity_score"] for o in trinity.score_window([hi, lo, mid], 1)}
        without = {o["row"]["sleeper_id"]: o["trinity_score"] for o in trinity.score_window([hi, lo], 1)}
        self.assertEqual(with_rb["1001"], without["1001"])      # the RB did not move the pool's mean/std
        self.assertEqual(with_rb["1003"], 5.0)                  # mid-pool metrics -> z of 0

    def test_z_is_clamped_at_2_5(self):
        pool = [agg(i) for i in range(1, 21)] + [agg(99, first_downs=500, rec_yards=5000, yac=900, rec=90, player_air_yards=240)]
        top = max(trinity.score_window(pool, 1), key=lambda o: o["trinity_score"])
        self.assertEqual(top["row"]["sleeper_id"], "1099")
        for f in trinity.Z_FIELDS:
            self.assertEqual(top[f"z_{f}"], 2.5)
        # 5 + .36*2.5 + .30*2.5 + .34*2.5 + .38*2.5 + .29*2.5 sums to 9.17499999... in IEEE doubles (JS and Python alike),
        # so the page shows 9.17, not the 9.18 that exact decimal arithmetic would round up to
        self.assertEqual(top["trinity_score"], 9.17)

    def test_zero_variance_does_not_divide_by_zero(self):
        out = trinity.score_window([agg(1), agg(2), agg(3)], 1)
        self.assertEqual({o["trinity_score"] for o in out}, {5.0})

    def test_filters(self):
        base = [agg(1), agg(2)]
        keep = lambda extra: {o["row"]["sleeper_id"] for o in trinity.score_window(base + extra, 17)}
        self.assertEqual(keep([agg(3, targets=4)]), {"1001", "1002"})            # below the 5-target floor of a 17-game window
        self.assertEqual(keep([agg(4, routes=0)]), {"1001", "1002"})
        self.assertEqual(keep([agg(5, games=0)]), {"1001", "1002"})
        self.assertEqual(keep([agg(6, pos="QB")]), {"1001", "1002"})
        self.assertIn("1007", keep([agg(7, targets=5)]))
        self.assertEqual(trinity.score_window([agg(1, pos="RB")], 1), [])        # no WR/TE pool, no scores

    def test_tiers_and_position_rank(self):
        self.assertEqual([trinity.tier("WR", s) for s in (7.7, 7.69, 6.7, 5.5, 4.9, 4.89)],
                         ["Elite", "Above League Average", "Above League Average", "League Average", "Below League Average", "Depth"])
        self.assertEqual([trinity.tier("TE", s) for s in (7.2, 6.6, 5.1, 5.09)], ["Elite", "Above League Average", "Below League Average", "Depth"])
        self.assertEqual(trinity.tier("RB", 7.7), "Elite")                      # RB use the WR bands
        out = trinity.score_window([agg(1, first_downs=6, rec_yards=90, yac=30, rec=8, player_air_yards=120),
                                    agg(2, first_downs=1, rec_yards=20, yac=2, rec=1, player_air_yards=10)], 1)
        self.assertEqual(sorted((o["row"]["sleeper_id"], o["position_rank"]) for o in out), [("1001", 1), ("1002", 2)])

    def test_window_sums_weeks_and_reports_window_games(self):
        w1 = [agg(1, rec=3, team="KC", team_air_yards=200), agg(2, team="KC", team_air_yards=200)]
        w2 = [agg(1, rec=5, team="DEN", team_air_yards=300), agg(3, team="DEN", team_air_yards=300)]
        rows, wg = trinity.window_of([w1, w2])
        p = next(r for r in rows if r["sleeper_id"] == "1001")
        self.assertEqual((p["games"], p["rec"], p["team"]), (2, 8, "DEN"))            # traded: latest team
        self.assertEqual(p["team_air_yards"], 300)       # his LATEST team's air yards over the window's weeks it has data for
        self.assertEqual(wg, 2)
        self.assertEqual(trinity.window_of([w1])[1], 1)

    def test_team_air_yards_counts_weeks_the_player_missed(self):
        # DD (verified live, 2025): a player who missed week 2 still gets his team's week-2 air yards in a 1..2 window
        w1 = [agg(1, team="KC", team_air_yards=200), agg(2, team="KC", team_air_yards=200)]
        w2 = [agg(2, team="KC", team_air_yards=250)]
        rows, _ = trinity.window_of([w1, w2])
        self.assertEqual({r["sleeper_id"]: r["team_air_yards"] for r in rows}, {"1001": 450, "1002": 450})
        self.assertEqual(next(r for r in rows if r["sleeper_id"] == "1001")["games"], 1)


class Env(TempEnv):
    def __enter__(self):
        super().__enter__()
        self.p = mock.patch.dict(os.environ, {"FDB_NOW": NOW, "DDFF_SUPABASE_URL": "https://x.supabase.co", "DDFF_SUPABASE_KEY": "pub",
                                              "DDFF_EMAIL": "me@example.com", "DDFF_PASSWORD": "pw-secret"})
        self.p.start()
        self.c = self.conn()
        seed_schedule_raw()
        ld = ScheduleLoader()
        for sc in fw.scopes(self.c, ld):
            assert not fw.load(self.c, ld, sc, apply=True)["failures"]
        ddff._state.update(token=None, exp=0.0, last=0.0)
        return self

    def __exit__(self, *exc):
        self.p.stop()
        return super().__exit__(*exc)

    def teams(self, season, st, week):
        return sorted({t for r in self.c.execute("""SELECT home_team, away_team FROM core_schedule
                        WHERE season = ? AND season_type = ? AND week = ?""", (season, st, week)) for t in r})

    def week_rows(self, season, week, per_team=6, **kw):
        out = []
        for ti, t in enumerate(self.teams(season, "REG", week)):
            for j in range(per_team):
                out.append(agg(ti * 10 + j, pos=("WR", "WR", "TE", "RB", "WR", "TE")[j], team=t, **kw))
        return out

    def seed(self, season, week, rows):
        return raw.write("ddff", "trinity_ftn_aggregates_week", f"{season}/REG{week:02d}", json.dumps(rows).encode(), "json", {}, len(rows), False)


class Client(unittest.TestCase):
    def test_missing_settings_name_the_variable_not_a_value(self):
        with Env():
            with mock.patch.dict(os.environ, {"DDFF_EMAIL": ""}), mock.patch.object(ddff.config, "env", side_effect=lambda n, d="": os.environ.get(n, d)):
                with self.assertRaises(ddff.DdffError) as cm:
                    ddff.login()
            self.assertIn("DDFF_EMAIL", str(cm.exception))

    def test_rpc_logs_in_once_and_sends_the_bearer(self):
        calls = []

        def fake(url, data=None, headers=None, timeout=60):
            calls.append((url, headers))
            if "/auth/v1/token" in url:
                return 200, {}, json.dumps({"access_token": "tok1", "expires_in": 3600}).encode()
            return 200, {}, b'[{"a": 1}]'
        with Env():
            with mock.patch.object(ddff.http, "request", side_effect=fake), mock.patch.object(ddff, "MIN_GAP_S", 0):
                body, params = ddff.rpc("trinity_ftn_aggregates_weeks", {"p_season": 2025, "p_weeks": [1]})
                ddff.rpc("trinity_ftn_aggregates_weeks", {"p_season": 2025, "p_weeks": [2]})
        self.assertEqual(body, b'[{"a": 1}]')
        self.assertEqual(sum("/auth/v1/token" in u for u, _ in calls), 1)
        self.assertEqual(calls[1][1]["Authorization"], "Bearer tok1")
        blob = json.dumps(params)
        self.assertNotIn("pw-secret", blob)
        self.assertNotIn("tok1", blob)
        self.assertNotIn("me@example.com", blob)

    def test_rejected_token_relogs_once(self):
        state = {"n": 0}

        def fake(url, data=None, headers=None, timeout=60):
            if "/auth/v1/token" in url:
                state["n"] += 1
                return 200, {}, json.dumps({"access_token": f"tok{state['n']}", "expires_in": 3600}).encode()
            if headers["Authorization"] == "Bearer tok1":
                raise urllib.error.HTTPError(url, 401, "no", {}, None)
            return 200, {}, b"[]"
        with Env():
            with mock.patch.object(ddff.http, "request", side_effect=fake), mock.patch.object(ddff, "MIN_GAP_S", 0):
                body, _ = ddff.rpc("f", {})
        self.assertEqual((body, state["n"]), (b"[]", 2))

    def test_error_payloads_raise_with_the_source_reason(self):
        import io
        for text, expect in ((b'{"message": "read_quota_exceeded", "code": "P0001"}', "read_quota_exceeded"),
                             (b'{"message": "membership_required"}', "membership_required")):
            def fake(url, data=None, headers=None, timeout=60, _t=text):
                if "/auth/v1/token" in url:
                    return 200, {}, b'{"access_token": "t", "expires_in": 3600}'
                return 200, {}, _t
            with Env():
                with mock.patch.object(ddff.http, "request", side_effect=fake), mock.patch.object(ddff, "MIN_GAP_S", 0):
                    with self.assertRaises(ddff.DdffError) as cm:
                        ddff.rpc("f", {})
                self.assertIn(expect, str(cm.exception))

    def test_a_non_list_answer_is_refused(self):
        def fake(url, data=None, headers=None, timeout=60):
            return (200, {}, b'{"access_token": "t", "expires_in": 3600}') if "/auth/v1/token" in url else (200, {}, b'"nope"')
        with Env():
            with mock.patch.object(ddff.http, "request", side_effect=fake), mock.patch.object(ddff, "MIN_GAP_S", 0):
                with self.assertRaises(ddff.DdffError):
                    ddff.rpc("f", {})

    def test_paged_reads_until_an_empty_page(self):
        pages = [[{"i": n} for n in range(250)], [{"i": 250}], []]
        offs = []

        def fake_rpc(fn, args):
            offs.append(args["_offset"])
            return json.dumps(pages[len(offs) - 1]).encode(), {"url": "u", "fn": fn, "args": "{}"}
        with mock.patch.object(ddff, "rpc", side_effect=fake_rpc):
            rows, _ = ddff.paged("gated_trinity_scores", {"_season": 2025})
        self.assertEqual((len(rows), offs), (251, [0, 250, 251]))


class AggregatesLoader(unittest.TestCase):
    def test_scopes_are_reg_weeks_up_to_17_from_2021(self):
        with Env() as env:
            ld = get("ddff.trinity_aggregates")
            sc = fw.scopes(env.c, ld)
            self.assertTrue(sc)
            self.assertEqual({s.season_type for s in sc}, {"REG"})
            self.assertEqual(max(s.week for s in sc if s.season == 2025), 17)       # never week 18, never a playoff week
            self.assertTrue(all(s.season >= 2021 for s in sc))
            self.assertEqual([s.week for s in sc if s.season == 2026], [1, 2])      # completed weeks only

    def test_documented_source_defects_are_never_offered(self):
        from fdb.loaders.ddff import SOURCE_DEFECTS
        self.assertEqual(sorted(SOURCE_DEFECTS), [(2021, "REG", 15)] + [(2024, "REG", w) for w in (14, 15, 16, 17)])
        with Env() as env:
            ld = get("ddff.trinity_aggregates")
            with mock.patch.object(type(ld), "unavailable", {(2025, "REG", 3): "defect"}):   # the fixture schedule is 2025-2026
                weeks = {(s.season, s.week) for s in fw.scopes(env.c, ld)}
                parts = set(fw.fetch_partitions(env.c, ld))
            self.assertNotIn((2025, 3), weeks)
            self.assertNotIn("2025/REG03", parts)            # and so it is never fetched either
            self.assertTrue({(2025, 2), (2025, 4)} <= weeks)

    def test_fetch_asks_for_exactly_that_week(self):
        with Env():
            ld = get("ddff.trinity_aggregates")
            with mock.patch.object(ddff, "rpc", return_value=(b"[]", {})) as r:
                ld.fetch("2025/REG07")
            self.assertEqual(r.call_args.args, ("trinity_ftn_aggregates_weeks", {"p_season": 2025, "p_weeks": [7]}))

    def test_full_week_loads_idempotently_with_source_names(self):
        with Env() as env:
            rows = env.week_rows(2026, 1)
            env.seed(2026, 1, rows)
            ld = get("ddff.trinity_aggregates")
            res = fw.load(env.c, ld, fw.Scope(2026, "REG", 1), apply=True)
            self.assertEqual(res["failures"], [])
            self.assertEqual(res["rows"], len(rows))
            r = env.c.execute("SELECT * FROM core_trinity_ftn_aggregates WHERE season = 2026 AND week = 1 LIMIT 1").fetchone()
            self.assertEqual((r["season_type"], r["pos"] in ("WR", "TE", "RB")), ("REG", True))
            ok, before, after = fw.check_idempotent(env.c, ld, fw.Scope(2026, "REG", 1))
            self.assertTrue(ok, (before, after))

    def test_partial_week_is_refused(self):
        with Env() as env:
            rows = [r for r in env.week_rows(2026, 1) if r["team"] not in env.teams(2026, "REG", 1)[:2]]
            env.seed(2026, 1, rows)
            res = fw.load(env.c, get("ddff.trinity_aggregates"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("scheduled teams missing" in f for f in res["failures"]), res["failures"])
            self.assertFalse(res["applied"])

    def test_truncated_week_and_odd_data_are_refused(self):
        for kw, expect in (({"per_team": 1}, "player rows"), ({"games": 2}, "games = 2"), ({"targets": -1}, "negative count")):
            with Env() as env:
                env.seed(2026, 1, env.week_rows(2026, 1, **kw))
                res = fw.load(env.c, get("ddff.trinity_aggregates"), fw.Scope(2026, "REG", 1), apply=True)
                self.assertTrue(any(expect in f for f in res["failures"]), (expect, res["failures"]))
                self.assertFalse(res["applied"])

    def test_missing_source_field_fails_the_load(self):
        with Env() as env:
            rows = [{k: v for k, v in r.items() if k != "first_downs"} for r in env.week_rows(2026, 1)]
            env.seed(2026, 1, rows)
            res = fw.load(env.c, get("ddff.trinity_aggregates"), fw.Scope(2026, "REG", 1), apply=True)
            self.assertTrue(any("first_downs" in f for f in res["failures"]), res["failures"])

    def test_in_season_raw_is_never_final_but_a_closed_season_is(self):
        with Env() as env:
            ld = get("ddff.trinity_aggregates")
            self.assertFalse(ld.raw_is_final(env.c, "2026/REG01"))
            self.assertTrue(ld.raw_is_final(env.c, "2025/REG01"))


class ScoresLoader(unittest.TestCase):
    @staticmethod
    def rows(n=220, season=2025):
        return [{"player_name": f"P {i}", "team": "KC", "position": ("WR", "TE", "RB")[i % 3], "sleeper_id": str(5000 + i),
                 "season": season, "trinity_score": 3 + (i % 50) / 10, "ppg": 10.5, "games": 15, "tier": "Depth", "rank": i + 1,
                 "first_downs": 40, "yprr": 1.5, "yac_per_game": 20.0, "rec_per_game": 4, "air_yard_share": 0.2} for i in range(n)]

    def test_only_closed_seasons_are_offered(self):
        with Env() as env:
            self.assertEqual([s.season for s in fw.scopes(env.c, get("ddff.trinity_scores"))], [2025])   # 2026 is in progress

    def test_loads_a_closed_season(self):
        with Env() as env:
            payload = json.dumps(self.rows()).encode()
            raw.write("ddff", "trinity_scores_season", "2025", payload, "json", {}, 220, True)
            ld = get("ddff.trinity_scores")
            res = fw.load(env.c, ld, fw.Scope(2025), apply=True)
            self.assertEqual(res["failures"], [])
            self.assertEqual(env.c.execute("SELECT COUNT(*), MIN(season_type) FROM core_trinity_scores").fetchone()[:], (220, "REG"))
            self.assertTrue(fw.check_idempotent(env.c, ld, fw.Scope(2025))[0])

    def test_other_season_score_range_and_size_are_refused(self):
        for rows, expect in ((self.rows(season=2024), "season(s)"), (self.rows(n=50), "truncated"),
                             ([{**r, "trinity_score": 11} for r in self.rows()], "outside 0-10")):
            with Env() as env:
                raw.write("ddff", "trinity_scores_season", "2025", json.dumps(rows).encode(), "json", {}, len(rows), True)
                res = fw.load(env.c, get("ddff.trinity_scores"), fw.Scope(2025), apply=True)
                self.assertTrue(any(expect in f for f in res["failures"]), (expect, res["failures"]))
                self.assertFalse(res["applied"])

    def test_owner_is_enforced(self):
        from fdb import registry
        with self.assertRaises(registry.OwnershipError):
            registry.assert_owner("ddff.trinity_scores", "core_trinity_ftn_aggregates")
        self.assertEqual(registry.owner_of("mart_trinity_week"), "trinity.build")


class Builder(unittest.TestCase):
    def setUp(self):
        self.env = Env().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        c = self.env.c
        for w in (1, 2):
            env_rows = self.env.week_rows(2026, w)
            env_rows = [dict(r, first_downs=r["first_downs"] + (i % 5), rec_yards=r["rec_yards"] + 3 * (i % 7)) for i, r in enumerate(env_rows)]
            ld = get("ddff.trinity_aggregates")
            self.env.seed(2026, w, env_rows)
            res = fw.load(c, ld, fw.Scope(2026, "REG", w), apply=True)
            self.assertEqual(res["failures"], [])
        # identity: one DD sleeper id resolves to the SAME gsis DD sent, one to a different one, the rest are unresolved
        for g in ("00-0000000", "00-0000001", "00-0009999"):
            c.execute("INSERT INTO players (gsis_id, display_name, players_source) VALUES (?, ?, 'nflverse_players')", (g, g))
        c.execute("INSERT INTO player_ids VALUES ('sleeper', '1000', '00-0000000', 'source_native', 't')")
        c.execute("INSERT INTO player_ids VALUES ('sleeper', '1001', '00-0009999', 'source_native', 't')")

    def test_marts_are_built_with_ids_joined_never_guessed(self):
        c = self.env.c
        res = trinity.build(c)
        self.assertEqual(res["failures"], [])
        n_wk = c.execute("SELECT COUNT(*) FROM mart_trinity_week").fetchone()[0]
        self.assertGreater(n_wk, 0)
        self.assertEqual(c.execute("SELECT gsis_id FROM mart_trinity_week WHERE week = 1 AND sleeper_id = '1000'").fetchone()[0], "00-0000000")
        self.assertIsNone(c.execute("SELECT gsis_id FROM mart_trinity_week WHERE week = 1 AND sleeper_id = '1002'").fetchone()[0])
        mism = c.execute("SELECT COUNT(*) FROM mart_trinity_week WHERE gsis_id IS NOT NULL AND gsis_id != player_gsis_id").fetchone()[0]
        self.assertEqual(mism, 2)                                      # sleeper 1001 in weeks 1 and 2
        lo, hi = c.execute("SELECT MIN(trinity_score), MAX(trinity_score) FROM mart_trinity_week").fetchone()
        self.assertTrue(0 <= lo <= hi <= 10)

    def test_through_week_one_equals_week_one_and_week_two_is_cumulative(self):
        c = self.env.c
        trinity.build(c)
        a = c.execute("SELECT sleeper_id, trinity_score FROM mart_trinity_week WHERE week = 1 ORDER BY 1").fetchall()
        b = c.execute("SELECT sleeper_id, trinity_score FROM mart_trinity_through_week WHERE week = 1 ORDER BY 1").fetchall()
        self.assertEqual([tuple(r) for r in a], [tuple(r) for r in b])
        g = c.execute("SELECT MAX(games) FROM mart_trinity_through_week WHERE week = 2").fetchone()[0]
        self.assertEqual(g, 2)

    def test_season_to_date_stops_at_a_missing_week_instead_of_bridging_it(self):
        c = self.env.c
        c.execute("DELETE FROM core_trinity_ftn_aggregates WHERE season = 2026 AND week = 1")   # week 1 gone, week 2 present
        trinity.build(c)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM mart_trinity_through_week WHERE season = 2026").fetchone()[0], 0)
        self.assertGreater(c.execute("SELECT COUNT(*) FROM mart_trinity_week WHERE season = 2026 AND week = 2").fetchone()[0], 0)

    def test_rebuild_is_idempotent_and_a_failed_check_rolls_back(self):
        c = self.env.c
        trinity.build(c)
        h1 = db.table_hash(c, "mart_trinity_week")
        trinity.build(c)
        self.assertEqual(h1, db.table_hash(c, "mart_trinity_week"))
        with mock.patch.object(trinity, "checks", return_value=["boom"]):
            res = trinity.build(c)
        self.assertEqual(res["failures"], ["boom"])
        self.assertEqual(h1, db.table_hash(c, "mart_trinity_week"))   # rolled back to the last good build


if __name__ == "__main__":
    unittest.main()
