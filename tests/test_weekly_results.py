"""Phase 11: MFL weeklyResults + lineups loaders. Offline: payloads are fixtures in the raw store.

The shapes are the ones the live probe returned (2026-10-03, league 30590): a franchise can play
SEVERAL games a week with one score; an unplayed week has no score and result 'T'; the starters
list equals the players marked `starter`; the starters' scores plus `adj_score` equal the score."""
import json
import os
import unittest
from unittest import mock

from fdb import leagues, loader as fw
from fdb.loaders import get
from tests.test_fantasy import FantasyEnv, TOML, mfl_league, write_raw

L = "11111"


def player(pid, status, score):
    return {"id": pid, "status": status, "score": score, "shouldStart": "1" if status == "starter" else "0"}


def side(fid, score, result, home, adj=None, lineup=None, extra=None):
    """One franchise element. lineup: [(pid, status, score)] -> starters/nonstarters/player/score."""
    lineup = lineup if lineup is not None else [(f"{fid}1", "starter", score), (f"{fid}2", "nonstarter", 3.0)]
    f = {"id": fid, "score": str(score), "result": result, "isHome": home, "opt_pts": str(score + 5),
         "optimal": ",".join(p[0] for p in lineup if p[1] == "starter"),
         "starters": ",".join(p[0] for p in lineup if p[1] == "starter"),
         "nonstarters": ",".join(p[0] for p in lineup if p[1] == "nonstarter"),
         "player": [player(*p) for p in lineup]}
    if adj is not None:
        f["adj_score"] = str(adj)
    f.update(extra or {})
    return f


def week_payload(week, matchups):
    """matchups: [[franchise, franchise] | [franchise]]  (a one-element list is the BARE-object quirk)."""
    m = [{"franchise": ms if len(ms) > 1 else ms[0]} for ms in matchups]
    return {"version": "1.0", "weeklyResults": {"week": str(week), "matchup": m}}


def two_games_week(week, s=(100.0, 90.0, 80.0, 70.0)):
    """Four franchises, each plays TWO games (a ring): A-B, B-C, C-D, D-A, with one score per franchise."""
    a, b, c, d = s
    res = lambda x, y: "W" if x > y else "L" if x < y else "T"
    return week_payload(week, [
        [side("0001", a, res(a, b), "1"), side("0002", b, res(b, a), "0")],
        [side("0002", b, res(b, c), "1"), side("0003", c, res(c, b), "0")],
        [side("0003", c, res(c, d), "1"), side("0004", d, res(d, c), "0")],
        [side("0004", d, res(d, a), "1"), side("0001", a, res(a, d), "0")]])


class Env(FantasyEnv):
    def seed(self, payloads):
        write_raw("mfl", "league", "2026/11111", mfl_league())
        for lid in ("mfl.league", "mfl.divisions", "mfl.conferences", "mfl.franchises"):
            self.load_all(lid)
        for week, obj in payloads.items():
            write_raw("mfl", "weeklyResults", f"2026/{L}/REG{week:02d}", obj)
        return {lid: [fw.load(self.c, get(lid), sc, apply=True) for sc in fw.scopes(self.c, get(lid)) if fw.raw_for(get(lid), sc)]
                for lid in ("mfl.weekly_results", "mfl.lineups")}


class Parse(unittest.TestCase):
    def test_every_game_is_a_row_with_its_opponent(self):
        _, rows = get("mfl.weekly_results").parse(json.dumps(two_games_week(1)).encode())
        self.assertEqual(len(rows), 8)
        self.assertEqual(sorted((r["id"], r["opponent_id"]) for r in rows),
                         [("0001", "0002"), ("0001", "0004"), ("0002", "0001"), ("0002", "0003"),
                          ("0003", "0002"), ("0003", "0004"), ("0004", "0001"), ("0004", "0003")])
        self.assertTrue(all(r["week"] == "1" for r in rows))

    def test_bare_object_matchup_is_a_bye(self):
        payload = week_payload(1, [[side("0001", 50.0, "W", "1")], [side("0002", 40.0, "L", "0"), side("0003", 30.0, "W", "1")]])
        _, rows = get("mfl.weekly_results").parse(json.dumps(payload).encode())
        self.assertEqual([(r["id"], r["opponent_id"]) for r in rows], [("0001", ""), ("0002", "0003"), ("0003", "0002")])

    def test_three_franchises_in_a_matchup_is_refused(self):
        payload = week_payload(1, [[side("0001", 1.0, "W", "1"), side("0002", 1.0, "L", "0"), side("0003", 1.0, "L", "0")]])
        with self.assertRaises(ValueError):
            get("mfl.weekly_results").parse(json.dumps(payload).encode())

    def test_lineup_players_once_per_franchise(self):
        fields, rows = get("mfl.lineups").parse(json.dumps(two_games_week(1)).encode())
        self.assertEqual(len(rows), 8)   # 4 franchises x 2 players, not x2 for the two games
        self.assertEqual({r["franchise_id"] for r in rows}, {"0001", "0002", "0003", "0004"})
        self.assertEqual(fields, ["id", "score", "shouldStart", "status"])

    def test_starters_list_must_match_player_status(self):
        pay = two_games_week(1)
        pay["weeklyResults"]["matchup"][0]["franchise"][0]["starters"] = "9999"
        with self.assertRaises(ValueError):
            get("mfl.lineups").parse(json.dumps(pay).encode())

    def test_two_games_must_share_one_lineup(self):
        pay = two_games_week(1)
        pay["weeklyResults"]["matchup"][3]["franchise"][1]["player"][1]["status"] = "starter"
        pay["weeklyResults"]["matchup"][3]["franchise"][1]["starters"] += ",00012"
        with self.assertRaises(ValueError):
            get("mfl.lineups").parse(json.dumps(pay).encode())


class Load(unittest.TestCase):
    def test_both_weeks_load_and_a_franchise_has_two_games(self):
        with Env() as env:
            res = env.seed({1: two_games_week(1), 2: two_games_week(2, (60.0, 70.0, 80.0, 90.0))})
            for lid, rs in res.items():
                self.assertEqual(len(rs), 2, lid)
                for r in rs:
                    self.assertEqual(r["failures"], [], (lid, r))
            n = env.c.execute("SELECT COUNT(*) FROM core_mfl_weekly_results WHERE week = 1").fetchone()[0]
            self.assertEqual(n, 8)
            games = env.c.execute("""SELECT COUNT(*) FROM core_mfl_weekly_results WHERE week = 1 AND id = '0001'""").fetchone()[0]
            self.assertEqual(games, 2)
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM core_mfl_lineups WHERE week = 1").fetchone()[0], 8)
            # a week's points count once per franchise: SUM over distinct franchises, not over games
            once = env.c.execute("SELECT SUM(s) FROM (SELECT MAX(score) s FROM core_mfl_weekly_results WHERE week = 1 GROUP BY id)").fetchone()[0]
            self.assertEqual(once, 340.0)

    def test_reload_is_idempotent(self):
        with Env() as env:
            env.seed({1: two_games_week(1), 2: two_games_week(2)})
            for lid in ("mfl.weekly_results", "mfl.lineups"):
                ld = get(lid)
                ok, _, _ = fw.check_idempotent(env.c, ld, fw.scopes(env.c, ld)[0])
                self.assertTrue(ok, lid)

    def test_unplayed_payload_is_refused(self):
        """An unplayed week: no score key at all, result 'T' for everyone. It must never become data."""
        def unplayed(null_scores):
            fr = [side("0001", 0, "T", "1"), side("0002", 0, "T", "0")]
            for f in fr:
                f.pop("score"), f.pop("opt_pts")
                if null_scores:
                    f["score"] = None
            return week_payload(1, [fr])
        with Env() as env:   # the contract catches the missing field
            res = env.seed({1: unplayed(False)})["mfl.weekly_results"][0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("missing expected fields" in f for f in res["failures"]), res["failures"])
        with Env() as env:   # a present-but-null score is caught by the post-write check
            fr = week_payload(1, [[side("0001", 0, "T", "1"), side("0002", 0, "T", "0")]])
            for f in fr["weeklyResults"]["matchup"][0]["franchise"]:
                f["score"], f["opt_pts"] = None, None
            res = env.seed({1: fr})["mfl.weekly_results"][0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("without a score" in f for f in res["failures"]), res["failures"])

    def test_result_that_disagrees_with_scores_fails(self):
        pay = two_games_week(1)
        pay["weeklyResults"]["matchup"][0]["franchise"][0]["result"] = "L"   # 100 vs 90 is a win
        with Env() as env:
            res = env.seed({1: pay})["mfl.weekly_results"][0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("scores say 'W'" in f for f in res["failures"]), res["failures"])

    def test_a_tie_is_a_tie(self):
        pay = week_payload(1, [[side("0001", 70.0, "T", "1"), side("0002", 70.0, "T", "0")]])
        with Env() as env:
            res = env.seed({1: pay})["mfl.weekly_results"][0]
            self.assertEqual(res["failures"], [])

    def test_missing_mirror_row_fails(self):
        with Env() as env:
            env.seed({})
            ld = get("mfl.weekly_results")
            env.c.execute("BEGIN")
            env.c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('x','x','x','x',1)")
            env.c.execute("""INSERT INTO core_mfl_weekly_results (season, season_type, week, league_id, id, opponent_id, score, result, load_id)
                             VALUES (2026,'REG',1,?,'0001','0002',70,'W',1)""", (L,))   # 0002's row against 0001 is absent
            fails = ld.checks(env.c, fw.Scope(2026, "REG", 1, league=L))
            env.c.execute("ROLLBACK")
            self.assertTrue(any("no mirror row" in f for f in fails), fails)

    def test_one_franchise_two_scores_fails(self):
        pay = two_games_week(1)
        pay["weeklyResults"]["matchup"][3]["franchise"][1]["score"] = "101.0"   # 0001's second game
        with Env() as env:
            res = env.seed({1: pay})["mfl.weekly_results"][0]
            self.assertTrue(any("different scores in its games" in f for f in res["failures"]), res["failures"])

    def test_franchise_outside_the_league_fails(self):
        pay = week_payload(1, [[side("0001", 70.0, "W", "1"), side("9999", 60.0, "L", "0")]])
        with Env() as env:
            res = env.seed({1: pay})["mfl.weekly_results"][0]
            self.assertTrue(any("not in core_mfl_franchises" in f for f in res["failures"]), res["failures"])

    def test_payload_for_another_week_is_refused(self):
        with Env() as env:
            res = env.seed({1: two_games_week(2)})["mfl.weekly_results"][0]   # W=1 answered with week 2
            self.assertFalse(res["applied"])
            self.assertTrue(any("week(s)" in f for f in res["failures"]), res["failures"])

    def test_scope_follows_the_schedule_and_end_week(self):
        with Env() as env:
            env.seed({})
            self.assertEqual([s.week for s in fw.scopes(env.c, get("mfl.weekly_results"))], [1, 2])   # NOW = 2026 weeks 1-2 complete
            self.assertEqual({s.season_type for s in fw.scopes(env.c, get("mfl.weekly_results"))}, {"REG"})


class Lineups(unittest.TestCase):
    def test_starters_add_to_the_score(self):
        pay = two_games_week(1)
        pay["weeklyResults"]["matchup"][0]["franchise"][0]["player"][0]["score"] = 99.0   # 0001's starter now 99, score says 100
        pay["weeklyResults"]["matchup"][3]["franchise"][1]["player"][0]["score"] = 99.0
        with Env() as env:
            res = env.seed({1: pay})["mfl.lineups"][0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("do not add to the franchise score" in f for f in res["failures"]), res["failures"])

    def test_adjustment_is_accounted_for(self):
        """2021 wk1 (live): score = starters - 1000, adj_score -1000 is carried."""
        lineup = [("0011", "starter", 40.0), ("0012", "starter", 60.0), ("0013", "nonstarter", 5.0)]
        a = side("0001", -900.0, "L", "1", adj=-1000, lineup=lineup)
        b = side("0002", 10.0, "W", "0")
        with Env() as env:
            res = env.seed({1: week_payload(1, [[a, b]])})
            for lid, rs in res.items():
                self.assertEqual(rs[0]["failures"], [], lid)
            self.assertEqual(env.c.execute("SELECT adj_score FROM core_mfl_weekly_results WHERE id = '0001'").fetchone()[0], -1000.0)

    def test_without_the_adjustment_the_same_week_fails(self):
        lineup = [("0011", "starter", 40.0), ("0012", "starter", 60.0)]
        a = side("0001", -900.0, "L", "1", lineup=lineup)    # score off by 1000 and no adj_score
        with Env() as env:
            res = env.seed({1: week_payload(1, [[a, side("0002", 10.0, "W", "0")]])})["mfl.lineups"][0]
            self.assertTrue(any("do not add" in f for f in res["failures"]), res["failures"])


class EmptyAndNonH2h(unittest.TestCase):
    EMPTY = {"version": "1.0", "weeklyResults": {"week": "2"}}

    def test_empty_playoff_week_loads_as_zero_rows(self):
        lg = mfl_league()
        lg["league"]["lastRegularSeasonWeek"] = "1"       # week 2 is a playoff week
        with Env() as env:
            write_raw("mfl", "league", "2026/11111", lg)
            for lid in ("mfl.league", "mfl.divisions", "mfl.conferences", "mfl.franchises"):
                env.load_all(lid)
            write_raw("mfl", "weeklyResults", f"2026/{L}/REG02", self.EMPTY)
            for lid in ("mfl.weekly_results", "mfl.lineups"):
                res = fw.load(env.c, get(lid), fw.Scope(2026, "REG", 2, league=L), apply=True)
                self.assertEqual(res["failures"], [], (lid, res))
                self.assertEqual(res["rows"], 0)

    def test_empty_regular_season_week_still_fails(self):
        with Env() as env:   # lastRegularSeasonWeek = 14 in the fixture league: week 2 is regular season
            write_raw("mfl", "league", "2026/11111", mfl_league())
            for lid in ("mfl.league", "mfl.divisions", "mfl.conferences", "mfl.franchises"):
                env.load_all(lid)
            write_raw("mfl", "weeklyResults", f"2026/{L}/REG02", self.EMPTY)
            res = fw.load(env.c, get("mfl.weekly_results"), fw.Scope(2026, "REG", 2, league=L), apply=True)
            self.assertFalse(res["applied"])
            self.assertIn("empty is never loaded", res["failures"][0])

    def test_league_without_head_to_head_offers_no_weeks(self):
        lg = mfl_league()
        lg["league"]["h2h"] = "ALL"
        with Env() as env:
            write_raw("mfl", "league", "2026/11111", lg)
            for lid in ("mfl.league", "mfl.divisions", "mfl.conferences", "mfl.franchises"):
                env.load_all(lid)
            self.assertEqual(fw.scopes(env.c, get("mfl.weekly_results")), [])
            self.assertEqual(fw.scopes(env.c, get("mfl.lineups")), [])
            self.assertEqual(len(fw.scopes(env.c, get("mfl.player_scores"))), 2)   # other loaders unaffected


class HistoryScopes(unittest.TestCase):
    def test_history_seasons_only_reach_loaders_that_ask(self):
        with Env() as env:
            p = env.dir / "hist.toml"
            p.write_text(TOML.replace("seasons = [2026]\n\n[[league]]\nplatform = \"sleeper\"",
                                      "seasons = [2026]\nhistory_seasons = [2025]\n\n[[league]]\nplatform = \"sleeper\"", 1),
                         encoding="utf-8")
            self.assertIn("history_seasons", p.read_text())
            with mock.patch.object(leagues, "PATH", p):
                seasons = lambda lid: sorted({s.season for s in fw.scopes(env.c, get(lid))})
                self.assertEqual(seasons("mfl.weekly_results"), [2025, 2026])
                self.assertEqual(seasons("mfl.franchises"), [2025, 2026])
                self.assertEqual(seasons("mfl.player_scores"), [2026])
                self.assertEqual(seasons("mfl.rosters"), [])   # snapshot grain: raw files, none seeded
                self.assertEqual(leagues.for_platform("mfl")[0].history_seasons, (2025,))


def proj_payload(week, n=150, blank=0, scale=0.7):
    rows = [{"id": f"{i:05d}", "score": "" if i < blank else str(round(i * scale, 2))} for i in range(1, n + 1)]
    return {"version": "1.0", "projectedScores": {"week": str(week), "playerScore": rows}}


class Projections(unittest.TestCase):
    """Phase 11: mfl.projected_scores. NOW = 2026-09-26: weeks 1-2 complete, week 3 is next."""

    def at(self, stamp):
        return mock.patch.dict(os.environ, {"FDB_NOW": stamp})

    def test_parse_blank_score_and_single_bare_object(self):
        one = {"projectedScores": {"week": "3", "playerScore": {"id": "13589", "score": ""}}}
        fields, rows = get("mfl.projected_scores").parse(json.dumps(one).encode())
        self.assertEqual((fields, rows), (["id", "score"], [{"id": "13589", "score": "", "week": "3"}]))

    def test_fetches_only_the_next_unplayed_week(self):
        """A completed week's list is partial after the games (live, wk3), so it is never fetched."""
        with Env() as env:
            env.seed({})
            self.assertEqual(fw.fetch_partitions(env.c, get("mfl.projected_scores")), ["2026/11111/REG03"])

    def test_week_past_end_week_is_not_requested(self):
        lg = mfl_league()
        lg["league"]["endWeek"] = "2"
        with Env() as env:
            write_raw("mfl", "league", "2026/11111", lg)
            for lid in ("mfl.league", "mfl.divisions", "mfl.conferences", "mfl.franchises"):
                env.load_all(lid)
            self.assertEqual(fw.fetch_partitions(env.c, get("mfl.projected_scores")), [])   # week 3 > endWeek: MFL would answer another week

    def test_never_final(self):
        with Env() as env:
            ld = get("mfl.projected_scores")
            self.assertFalse(ld.raw_is_final(env.c, "2026/11111/REG02"))
            self.assertFalse(ld.raw_is_final(env.c, "2026/11111/REG03"))

    def test_every_fetch_of_an_unplayed_week_is_a_snapshot(self):
        with Env() as env:
            env.seed({})
            with self.at("2026-09-26T17:00:00Z"):
                write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(3))
            with self.at("2026-09-27T09:00:00Z"):
                write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(3, scale=0.8))
            res = env.load_all("mfl.projected_scores")
            self.assertEqual(len(res), 2)
            for r in res:
                self.assertEqual(r["failures"], [], r)
            snaps = env.c.execute("SELECT snapshot_at, COUNT(*), MAX(score) FROM core_mfl_projected_scores GROUP BY 1 ORDER BY 1").fetchall()
            self.assertEqual([(s[1], s[2]) for s in snaps], [(150, 105.0), (150, 120.0)])   # history kept: the numbers moved
            self.assertEqual({r[0] for r in env.c.execute("SELECT week FROM core_mfl_projected_scores")}, {3})

    def test_reload_is_idempotent(self):
        with Env() as env:
            env.seed({})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(3))
            env.load_all("mfl.projected_scores")
            ld = get("mfl.projected_scores")
            ok, _, _ = fw.check_idempotent(env.c, ld, fw.scopes(env.c, ld)[0])
            self.assertTrue(ok)

    def test_payload_for_another_week_is_refused(self):
        with Env() as env:
            env.seed({})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(2))   # W=3 answered with week 2
            res = env.load_all("mfl.projected_scores")[0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("week(s)" in f for f in res["failures"]), res["failures"])

    def test_too_few_players_and_too_many_blanks_fail(self):
        with Env() as env:
            env.seed({})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(3, n=40))
            res = env.load_all("mfl.projected_scores")[0]
            self.assertTrue(any("only 40 projected players" in f for f in res["failures"]), res["failures"])
        with Env() as env:
            env.seed({})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(3, blank=40))
            res = env.load_all("mfl.projected_scores")[0]
            self.assertTrue(any("projections are blank" in f for f in res["failures"]), res["failures"])

    def test_implausible_score_fails(self):
        with Env() as env:
            env.seed({})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", proj_payload(3, scale=20.0))   # 150 * 20 = 3000
            res = env.load_all("mfl.projected_scores")[0]
            self.assertTrue(any("beyond +-1000" in f for f in res["failures"]), res["failures"])

    def test_empty_placeholder_entry_is_not_a_row_but_a_score_without_an_id_is_refused(self):
        """Live: every response ends with {"id": "", "score": ""} (found by a NOT NULL failure on the first load)."""
        with Env() as env:
            env.seed({})
            pay = proj_payload(3)
            pay["projectedScores"]["playerScore"].append({"id": "", "score": ""})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", pay)
            res = env.load_all("mfl.projected_scores")[0]
            self.assertEqual(res["failures"], [], res)
            self.assertEqual(res["rows"], 150)
        with Env() as env:
            env.seed({})
            pay = proj_payload(3)
            pay["projectedScores"]["playerScore"].append({"id": "", "score": "12.5"})
            write_raw("mfl", "projectedScores", "2026/11111/REG03", pay)
            res = env.load_all("mfl.projected_scores")[0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("no player id" in f for f in res["failures"]), res["failures"])

    def test_registered_weekly_after_the_results_loaders(self):
        from fdb import registry
        self.assertIn("mfl.projected_scores", registry.weekly_loaders())


class Registry(unittest.TestCase):
    def test_both_tables_are_owned_and_weekly_in_order(self):
        from fdb import registry
        self.assertEqual(registry.owner_of("core_mfl_weekly_results"), "mfl.weekly_results") if hasattr(registry, "owner_of") else None
        order = registry.weekly_loaders()
        self.assertLess(order.index("mfl.weekly_results"), order.index("mfl.lineups"))   # the fetcher runs first


if __name__ == "__main__":
    unittest.main()
