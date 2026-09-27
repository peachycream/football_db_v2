"""Phase 3: MFL / Sleeper loaders, the league scope dimension, roster snapshots,
the ownership marts, the Sleeper identity source, and app state across a rebuild.
Offline: every payload is a fixture written into the raw store."""
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from fdb import builders, db, identity, leagues, loader as fw, mfl, raw, rebuild
from fdb.loaders import get
from fdb.loaders.nflverse_schedules import ScheduleLoader
from tests.helpers import TempEnv, seed_schedule_raw

NOW = "2026-09-26T17:00:00Z"   # 2026 weeks 1-2 complete, week 3 not

TOML = """
[[league]]
platform = "mfl"
league_id = "11111"
name = "Conf League"
my_franchise = "0002"
seasons = [2026]

[[league]]
platform = "sleeper"
league_id = "999"
name = "Sleeper League"
my_franchise = "2"
seasons = [2026]
"""


def mfl_league(unit="CONFERENCE", rpp="1", franchises=None):
    fr = franchises if franchises is not None else [
        {"id": "0001", "name": "A", "division": "00", "email": "a@example.com"},
        {"id": "0002", "name": "B", "division": "00"},
        {"id": "0003", "name": "C", "division": "01"},
        {"id": "0004", "name": "D", "division": "01"}]
    lg = {"id": "11111", "name": "Conf League", "baseURL": "https://www99.myfantasyleague.com",
          "rostersPerPlayer": rpp, "playerLimitUnit": unit, "rosterSize": "30", "taxiSquad": "3",
          "injuredReserve": "0", "startWeek": "1", "endWeek": "17", "lastRegularSeasonWeek": "14",
          "keeperType": "dynasty", "h2h": "YES", "precision": "2", "starters": {"count": "10"},
          "franchises": {"count": str(len(fr)), "franchise": fr},
          "divisions": {"count": "2", "division": [{"id": "00", "name": "East", "conference": "00"},
                                                    {"id": "01", "name": "West", "conference": "01"}]}}
    if unit == "CONFERENCE":
        lg["conferences"] = {"count": "2", "conference": [{"id": "00", "name": "AFC"}, {"id": "01", "name": "NFC"}]}
    return {"version": "1.0", "league": lg}


def mfl_rosters(pairs):
    """pairs: [(franchise, player_id, status)]. One-player franchises come back as a
    BARE OBJECT, exactly like MFL's JSON (the one-element-list quirk)."""
    by = {}
    for f, p, st in pairs:
        by.setdefault(f, []).append({"id": p, "status": st})
    fr = [{"id": f, "week": "3", "player": ps[0] if len(ps) == 1 else ps} for f, ps in sorted(by.items())]
    return {"version": "1.0", "rosters": {"franchise": fr[0] if len(fr) == 1 else fr}}


def mfl_players(extra=()):
    base = [{"id": "13589", "name": "Allen, Josh", "position": "QB", "team": "BUF", "draft_year": "2018"},
            {"id": "13592", "name": "Darnold, Sam", "position": "QB", "team": "SEA", "draft_year": "2018"},
            {"id": "0815", "name": "Manning, Arch", "position": "QB", "team": "FA"}]
    return {"version": "1.0", "players": {"player": base + list(extra)}}


def write_raw(source, endpoint, partition, obj, final=False):
    """As fw.fetch would write it, including the loader's retention policy."""
    payload = json.dumps(obj).encode()
    retention = "daily" if endpoint == "rosters" else "keep3"
    return raw.write(source, endpoint, partition, payload, "json", {"fixture": True}, 1, final, retention=retention)


class FantasyEnv(TempEnv):
    def __enter__(self):
        super().__enter__()
        p = self.dir / "my_franchises.toml"
        p.write_text(TOML, encoding="utf-8")
        self.patches = [mock.patch.object(leagues, "PATH", p), mock.patch.dict(os.environ, {"FDB_NOW": NOW}),
                        mock.patch.object(get("mfl.players").__class__, "MIN_ROWS", 1)]
        for x in self.patches:
            x.start()
        self.c = self.conn()
        seed_schedule_raw()
        ld = ScheduleLoader()
        for sc in fw.scopes(self.c, ld):
            assert not fw.load(self.c, ld, sc, apply=True)["failures"]
        return self

    def __exit__(self, *exc):
        for x in self.patches:
            x.stop()
        return super().__exit__(*exc)

    def load_all(self, lid):
        ld = get(lid)
        out = []
        for sc in fw.scopes(self.c, ld):
            out.append(fw.load(self.c, ld, sc, apply=True))
        return out

    def seed_mfl(self, league=None, rosters=None):
        write_raw("mfl", "league", "2026/11111", league or mfl_league())
        write_raw("mfl", "players", "2026/11111", mfl_players())
        if rosters is not None:
            write_raw("mfl", "rosters", "2026/11111", rosters)
        results = {}
        for lid in ("mfl.league", "mfl.divisions", "mfl.conferences", "mfl.franchises", "mfl.players", "mfl.rosters"):
            results[lid] = self.load_all(lid)
        return results


class MflQuirks(unittest.TestCase):
    def test_as_list(self):
        self.assertEqual(mfl.as_list(None), [])
        self.assertEqual(mfl.as_list({"id": "1"}), [{"id": "1"}])
        self.assertEqual(mfl.as_list([{"id": "1"}, {"id": "2"}]), [{"id": "1"}, {"id": "2"}])

    def test_bare_object_franchise_and_player_parse(self):
        _, rows = get("mfl.rosters").parse(json.dumps(mfl_rosters([("0001", "13589", "ROSTER")])).encode())
        self.assertEqual(rows, [{"id": "13589", "status": "ROSTER", "franchise_id": "0001", "week": "3"}])

    def test_rules_text_nodes_and_single_rule(self):
        payload = {"rules": {"positionRules": {"positions": "QB", "rule": {
            "event": {"$t": "PY"}, "range": {"$t": "0-999"}, "points": {"$t": "*0.04"}}}}}
        _, rows = get("mfl.rules").parse(json.dumps(payload).encode())
        self.assertEqual(rows, [{"event": "PY", "range": "0-999", "points": "*0.04", "positions": "QB"}])

    def test_error_payload_is_never_data(self):
        with self.assertRaises(mfl.MflError):
            mfl._check(b'{"error": {"$t": "API Key Validation Failed"}}', "league")

    def test_429_exhausted_starts_cooldown(self):
        err = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        with mock.patch.object(mfl.http, "request", side_effect=err), mock.patch.object(mfl.time, "sleep"), \
                mock.patch.object(mfl, "_cooldown_until", [0.0]), mock.patch.object(mfl, "interval", [0.0]):
            with self.assertRaises(mfl.MflError):
                mfl._get("https://x/2026/export?TYPE=rosters", None)
            with mock.patch.object(mfl.http, "request") as never:  # fails fast, no call made
                with self.assertRaises(mfl.MflError):
                    mfl._get("https://x/2026/export?TYPE=rosters", None)
                never.assert_not_called()


class MflLoaders(unittest.TestCase):
    def test_league_scopes_come_from_config(self):
        with FantasyEnv() as env:
            self.assertEqual([s.label for s in fw.scopes(env.c, get("mfl.league"))], ["season=2026/league=11111"])
            got = [s.label for s in fw.scopes(env.c, get("mfl.player_scores"))]
            self.assertEqual(got, ["season=2026/REG/week=1/league=11111", "season=2026/REG/week=2/league=11111"])

    def test_pools_capacity_and_mart(self):
        # 13589 on 0001 (AFC) and 0003 (NFC): legal, one owner per conference.
        ros = mfl_rosters([("0001", "13589", "ROSTER"), ("0003", "13589", "TAXI_SQUAD"),
                           ("0002", "13592", "ROSTER"), ("0004", "0815", "ROSTER")])
        with FantasyEnv() as env:
            res = env.seed_mfl(rosters=ros)
            for lid, rs in res.items():
                for r in rs:
                    self.assertEqual(r["failures"], [], (lid, r))
            self.assertEqual(env.c.execute("SELECT COUNT(*) FROM core_mfl_franchises").fetchone()[0], 4)
            self.assertIsNone(env.c.execute("SELECT * FROM pragma_table_info('core_mfl_franchises') WHERE name = 'email'").fetchone())
            builders.BUILDERS["fantasy.config"](env.c)
            rows = env.c.execute("""SELECT source_player_id, franchise_id, pool_name, pool_capacity, is_mine, slot
                                    FROM mart_roster_ownership ORDER BY 1, 2""").fetchall()
            self.assertEqual([tuple(r) for r in rows], [
                ("0815", "0004", "NFC", 1, 0, "roster"), ("13589", "0001", "AFC", 1, 0, "roster"),
                ("13589", "0003", "NFC", 1, 0, "taxi"), ("13592", "0002", "AFC", 1, 1, "roster")])
            unres = env.c.execute("SELECT source_player_id, category FROM mart_roster_unresolved ORDER BY 1").fetchall()
            # no identity built here: every id is listed, the devy one as devy
            self.assertEqual([tuple(u) for u in unres], [("0815", "devy"), ("13589", "nfl_unmapped"),
                                                         ("13589", "nfl_unmapped"), ("13592", "nfl_unmapped")])

    def test_two_owners_in_one_pool_fails_the_load(self):
        ros = mfl_rosters([("0001", "13589", "ROSTER"), ("0002", "13589", "ROSTER")])  # both AFC
        with FantasyEnv() as env:
            res = env.seed_mfl(rosters=ros)["mfl.rosters"][0]
            self.assertFalse(res["applied"])
            self.assertTrue(any("exceed rostersPerPlayer=1" in f for f in res["failures"]), res["failures"])

    def test_capacity_two_allows_two_owners(self):
        ros = mfl_rosters([("0001", "13589", "ROSTER"), ("0002", "13589", "ROSTER")])
        with FantasyEnv() as env:
            res = env.seed_mfl(league=mfl_league(unit="DIVISION", rpp="2"), rosters=ros)
            self.assertEqual(res["mfl.rosters"][0]["failures"], [])

    def test_empty_conferences_only_when_pools_are_not_conferences(self):
        with FantasyEnv() as env:
            res = env.seed_mfl(league=mfl_league(unit="DIVISION"))
            self.assertEqual(res["mfl.conferences"][0]["failures"], [])
        lg = mfl_league()
        del lg["league"]["conferences"]  # CONFERENCE pools but no conferences: refused
        with FantasyEnv() as env:
            res = env.seed_mfl(league=lg)
            self.assertIn("empty is never loaded", res["mfl.conferences"][0]["failures"][0])

    def test_my_franchise_must_exist(self):
        fr = [{"id": "0001", "name": "A", "division": "00"}, {"id": "0003", "name": "C", "division": "01"},
              {"id": "0004", "name": "D", "division": "01"}, {"id": "0005", "name": "E", "division": "00"}]
        with FantasyEnv() as env:
            res = env.seed_mfl(league=mfl_league(franchises=fr))
            self.assertTrue(any("my franchise 0002" in f for f in res["mfl.franchises"][0]["failures"]))

    def test_snapshots_keep_history_and_sync_with_retention(self):
        with FantasyEnv() as env:
            env.seed_mfl(rosters=mfl_rosters([("0001", "13589", "ROSTER")]))
            with mock.patch.dict(os.environ, {"FDB_NOW": "2026-09-27T17:00:00Z"}):
                write_raw("mfl", "rosters", "2026/11111", mfl_rosters([("0002", "13589", "ROSTER")]))
            env.load_all("mfl.rosters")
            snaps = env.c.execute("SELECT snapshot_at, franchise_id FROM core_mfl_rosters ORDER BY 1").fetchall()
            self.assertEqual([s[1] for s in snaps], ["0001", "0002"])  # history kept
            builders.BUILDERS["fantasy.config"](env.c)
            self.assertEqual(env.c.execute("SELECT franchise_id FROM mart_roster_ownership").fetchall()[0][0], "0002")
            # a second fetch the same UTC day supersedes the earlier one; core follows raw
            with mock.patch.dict(os.environ, {"FDB_NOW": "2026-09-27T18:00:00Z"}):
                write_raw("mfl", "rosters", "2026/11111", mfl_rosters([("0003", "13589", "ROSTER")]))
            env.load_all("mfl.rosters")
            self.assertEqual(fw.sync_snapshots(env.c, get("mfl.rosters")), 1)
            got = [r[0] for r in env.c.execute("SELECT franchise_id FROM core_mfl_rosters ORDER BY snapshot_at")]
            self.assertEqual(got, ["0001", "0003"])

    def test_snapshot_reload_is_idempotent(self):
        with FantasyEnv() as env:
            env.seed_mfl(rosters=mfl_rosters([("0001", "13589", "ROSTER")]))
            ld = get("mfl.rosters")
            ok, _, _ = fw.check_idempotent(env.c, ld, fw.scopes(env.c, ld)[-1])
            self.assertTrue(ok)

    def test_scores_stop_at_end_week_and_refuse_another_weeks_payload(self):
        with FantasyEnv() as env:
            lg = mfl_league()
            lg["league"]["endWeek"] = "1"
            env.seed_mfl(league=lg)
            ld = get("mfl.player_scores")
            self.assertEqual([s.week for s in fw.scopes(env.c, ld)], [1])   # week 2 is past endWeek
            # MFL answers W=2 beyond endWeek with week 1's scores: refused, never stored as week 2
            with self.assertRaises(ValueError):
                ld.scope_rows([{"id": "13589", "week": "1", "score": "5"}], fw.Scope(2026, "REG", 2, league="11111"))

    def test_scores_raw_final_only_after_corrections_window(self):
        with FantasyEnv() as env:
            ld = get("mfl.player_scores")
            self.assertFalse(ld.raw_is_final(env.c, "2026/11111/REG02"))   # week 2 ended 09-22
            with mock.patch.dict(os.environ, {"FDB_NOW": "2026-10-05T00:00:00Z"}):
                self.assertTrue(ld.raw_is_final(env.c, "2026/11111/REG02"))


class Sleeper(unittest.TestCase):
    def league(self, season="2026", lid="999"):
        return {"league_id": lid, "name": "Sleeper League", "season": season, "status": "in_season",
                "total_rosters": 2, "previous_league_id": "888", "settings": {}, "scoring_settings": {"rec": 1},
                "roster_positions": ["QB"]}

    def test_league_payload_for_another_season_is_refused(self):
        with FantasyEnv() as env:
            write_raw("sleeper", "league", "2026/999", self.league(season="2025"))
            res = env.load_all("sleeper.league")[0]
            self.assertTrue(any("rolls league ids yearly" in f for f in res["failures"]), res)

    def test_rosters_flags_and_stray_ids(self):
        ld = get("sleeper.rosters")
        rosters = [{"roster_id": 1, "owner_id": "u1", "players": ["10", "11"], "starters": ["10"], "taxi": ["11"],
                    "reserve": None}]
        _, rows = ld.parse(json.dumps(rosters).encode())
        self.assertEqual([(r["player_id"], r["in_starters"], r["in_taxi"]) for r in rows], [("10", 1, 0), ("11", 0, 1)])
        rosters[0]["reserve"] = ["12"]  # an id not in `players` would be silently dropped: refuse
        with self.assertRaises(ValueError):
            ld.parse(json.dumps(rosters).encode())


class SleeperIdentity(unittest.TestCase):
    def build(self, env, sleeper_rows):
        from tests.test_identity import seeded
        c = seeded(env)
        lid = c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('t','all','',  '',0)").lastrowid
        for r in sleeper_rows:
            cols = list(r)
            c.execute(f"INSERT INTO core_sleeper_players ({', '.join(cols)}, load_id) VALUES ({', '.join('?' * len(cols))}, ?)",
                      [*r.values(), lid])
        identity.build(c)
        return c

    def test_swapped_gsis_is_refused_by_the_name_check(self):
        with TempEnv() as env:
            c = self.build(env, [{"player_id": "90001", "full_name": "Ryan Izzo", "gsis_id": " 00-0034270"}])
            self.assertIsNone(c.execute("SELECT 1 FROM player_ids WHERE source='sleeper' AND source_id='90001'").fetchone())
            q = c.execute("SELECT reason FROM identity_quarantine WHERE source='sleeper' AND source_id='90001'").fetchone()
            self.assertIn("name disagrees", q[0])

    def test_native_gsis_with_whitespace_maps(self):
        with TempEnv() as env:
            c = self.build(env, [{"player_id": "90002", "full_name": "Tyler Conklin", "gsis_id": " 00-0034270 "}])
            # Conklin already has sleeper 5133/5094 from the roster fixture: one id per human per source
            got = c.execute("SELECT gsis_id FROM player_ids WHERE source='sleeper' AND source_id='90002'").fetchone()
            self.assertIsNone(got)
            self.assertIn("already has sleeper id", c.execute(
                "SELECT reason FROM identity_quarantine WHERE source_id='90002'").fetchone()[0])

    def test_single_bridge_needs_birth_date(self):
        with TempEnv() as env:
            # espn 3915486 is Conklin's in the fixture; wrong birth date -> not mapped
            c = self.build(env, [{"player_id": "90003", "full_name": "Tyler Conklin", "espn_id": "3915486",
                                  "birth_date": "1990-01-01"}])
            self.assertIsNone(c.execute("SELECT 1 FROM player_ids WHERE source_id='90003'").fetchone())


class AppStateSurvivesRebuild(unittest.TestCase):
    def test_wishlist_round_trip(self):
        from tests.helpers import seed_identity_raw
        from fdb.loaders.dp_playerids import DpPlayerIdsLoader
        from fdb.loaders.nflverse_players import PlayersLoader
        with TempEnv(), mock.patch.object(PlayersLoader, "MIN_ROWS", 10), mock.patch.object(DpPlayerIdsLoader, "MIN_ROWS", 10):
            seed_schedule_raw()
            seed_identity_raw()
            self.assertEqual(rebuild.run(), 0)
            c = db.connect()
            c.execute("INSERT INTO app_wishlist (gsis_id, note, priority, created_at) VALUES ('00-0034270', 'n', 2, '2026-09-01 00:00:00')")
            c.execute("INSERT INTO app_wishlist_priority (gsis_id, league_key, priority) VALUES ('00-0034270', 'mfl:30590', 1)")
            c.close()
            self.assertEqual(rebuild.run(), 0)
            c = db.connect()
            self.assertEqual([tuple(r) for r in c.execute("SELECT gsis_id, note, priority, created_at FROM app_wishlist")],
                             [("00-0034270", "n", 2, "2026-09-01 00:00:00")])
            self.assertEqual([tuple(r) for r in c.execute("SELECT league_key, priority FROM app_wishlist_priority")],
                             [("mfl:30590", 1)])
            h1 = db.content_hash(c)
            c.close()
            self.assertEqual(rebuild.run(), 0)
            self.assertEqual(db.content_hash(db.connect()), h1)


class WishlistImport(unittest.TestCase):
    def test_exact_keys_only(self):
        from fdb import wishlist_import
        from tests.test_identity import seeded
        with TempEnv() as env:
            v2 = seeded(env)
            identity.build(v2)
            v1 = sqlite3.connect(":memory:")
            v1.executescript("""
              CREATE TABLE players (player_id TEXT, full_name TEXT, birth_date TEXT, gsis_id TEXT);
              CREATE TABLE player_source_ids (player_id TEXT, source TEXT, source_player_id TEXT);
              CREATE TABLE draft_wishlist (player_id TEXT, source_context TEXT, note TEXT, priority INT, created_at TEXT);
              CREATE TABLE draft_wishlist_priority (player_id TEXT, league_id TEXT, priority INT, updated_at TEXT);
              INSERT INTO players VALUES ('conklin_tyler', 'Tyler Conklin', '1995-07-30', '00-0034270'),
                                         ('nobody_x', 'Nobody X', NULL, NULL),
                                         ('liar_y', 'Kevin Smith', NULL, '00-0034270');
              INSERT INTO player_source_ids VALUES ('conklin_tyler', 'mfl', '13675');
              INSERT INTO draft_wishlist VALUES ('conklin_tyler', 'player:2026', NULL, 1, '2026-08-01'),
                                                ('nobody_x', 'player:2026', NULL, NULL, '2026-08-02'),
                                                ('liar_y', 'player:2026', NULL, NULL, '2026-08-03');
              INSERT INTO draft_wishlist_priority VALUES ('conklin_tyler', 'mfl:30590:2026', 3, '2026-08-01');
            """)
            rows, prio, unmapped = wishlist_import.plan(v1, v2)
            self.assertEqual([r["gsis_id"] for r in rows], ["00-0034270"])
            self.assertEqual(prio, [{"gsis_id": "00-0034270", "league_key": "mfl:30590", "priority": 3, "updated_at": "2026-08-01"}])
            self.assertEqual(sorted(u["slug"] for u in unmapped), ["liar_y", "nobody_x"])
