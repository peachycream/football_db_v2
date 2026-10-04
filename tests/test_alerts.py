"""Phase 12: injury-feed loaders, the alert engine's decisions, its state, and the ntfy sender.
Offline: feeds are fixtures in the raw store; the network is never touched (notify's http is mocked)."""
import csv
import gzip
import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fdb import alerts, config, gameday, http, loader as fw, notify, raw
from fdb.loaders import get
from fdb.loaders.injuries import EspnInjuriesLoader, MflInjuriesLoader, NflInjuriesLoader
from tests.test_fantasy import FantasyEnv

NFL_FIELDS = ["season", "season_type", "game_type", "team", "week", "gsis_id", "position", "full_name", "first_name",
              "last_name", "report_primary_injury", "report_secondary_injury", "report_status",
              "practice_primary_injury", "practice_secondary_injury", "practice_status"]
FULL, LIMITED, DNP = ("Full Participation in Practice", "Limited Participation in Practice", "Did Not Participate In Practice")


def nfl_csv(rows):
    """rows: dicts with any of NFL_FIELDS; season/season_type/game_type/team default to 2026 REG BUF."""
    out = io.StringIO()
    w = csv.DictWriter(out, NFL_FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({"season": 2026, "season_type": "REG", "game_type": "REG", "team": "BUF", "position": "WR",
                    "full_name": "N N", **r})
    return out.getvalue().encode()


_tick = [0]


def tick():
    """raw.write never overwrites and names a file by the clock, so each fixture write moves FDB_NOW on."""
    _tick[0] += 1
    base = datetime.fromisoformat(os.environ["FDB_NOW"].replace("Z", "+00:00"))
    os.environ["FDB_NOW"] = (base + timedelta(seconds=_tick[0])).isoformat()


def put_nfl(rows, season=2026):
    tick()
    payload = nfl_csv(rows)
    raw.write("nflverse", "injuries", str(season), payload, "csv", {"fixture": True}, len(rows), False)


def put_mfl(rows, week="3", season=2026, timestamp="1790000000"):
    tick()
    payload = json.dumps({"version": "1.0", "injuries": {"timestamp": timestamp, "week": week,
                                                         "injury": rows if len(rows) != 1 else rows[0]}}).encode()
    raw.write("mfl", "injuries", "all", payload, "json", {"fixture": True, "season": season}, len(rows), False)


def espn_entry(name, pid, team, status, date, fantasy=None, comment="note", pos="WR", injury="Knee"):
    return {"id": "-1", "status": status, "date": date, "shortComment": comment, "longComment": "long " + comment,
            "athlete": {"displayName": name, "team": {"abbreviation": team}, "position": {"abbreviation": pos},
                        "links": [{"href": f"https://www.espn.com/nfl/player/_/id/{pid}/x"},
                                  {"href": f"https://www.espn.com/nfl/player/stats/_/id/{pid}/x"}]},
            **({"details": {"fantasyStatus": {"description": fantasy}, "type": injury, "location": "Leg"}} if fantasy else {})}


def espn_payload(entries, season_type=2, year=2026, ts="2026-09-27T15:00:00Z"):
    groups = {}
    for e in entries:
        groups.setdefault(e["athlete"]["team"]["abbreviation"], []).append(e)
    return {"timestamp": ts, "status": "success", "season": {"year": year, "type": season_type, "displayName": str(year)},
            "injuries": [{"id": "1", "displayName": t, "injuries": v} for t, v in groups.items()]}


def put_espn(entries, **kw):
    tick()
    payload = json.dumps(espn_payload(entries, **kw)).encode()
    raw.write("espn", "injuries", "all", payload, "json", {"fixture": True}, len(entries), False)


def load_espn(c):
    return fw.load(c, get("espn.injuries"), fw.Scope(0), apply=True)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def load_nfl(c, season=2026):
    return fw.load(c, get("nflverse.injuries"), fw.Scope(season), apply=True)


def load_mfl(c):
    return fw.load(c, get("mfl.injuries"), fw.Scope(0), apply=True)


def load_feeds(c, season=2026):
    return [load_nfl(c, season), load_mfl(c)]


class Env(FantasyEnv):
    """FantasyEnv's clock is 2026-09-26: weeks 1-2 complete, week 3 live -> the report week is REG 3."""

    def __enter__(self):
        super().__enter__()
        self.patches2 = [mock.patch.object(NflInjuriesLoader, "ROWS_PER_WEEK", (1, 700)),
                         mock.patch.object(MflInjuriesLoader, "ROWS", (1, 3000)),
                         mock.patch.object(EspnInjuriesLoader, "ROWS", (1, 3000))]
        for p in self.patches2:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches2:
            p.stop()
        return super().__exit__(*exc)

    def person(self, gsis, name, mfl_id=None, pos="WR", team="BUF", espn_id=None):
        self.c.execute("INSERT INTO players (gsis_id, display_name, position, latest_team, players_source) VALUES (?,?,?,?, 'rosters_weekly')",
                       (gsis, name, pos, team))
        if mfl_id:
            self.c.execute("INSERT INTO player_ids (source, source_id, gsis_id, method, evidence) VALUES ('mfl',?,?,'id_map','test')",
                           (mfl_id, gsis))
        if espn_id:
            self.c.execute("INSERT INTO player_ids (source, source_id, gsis_id, method, evidence) VALUES ('espn',?,?,'id_map','test')",
                           (espn_id, gsis))


class Loaders(unittest.TestCase):
    def test_nfl_loads_week_rows_and_keeps_source_names(self):
        with Env() as e:
            put_nfl([{"week": 3, "gsis_id": "00-1", "report_status": "Out", "report_primary_injury": "Knee", "practice_status": DNP},
                     {"week": 3, "gsis_id": "00-2", "practice_status": FULL}])
            r = load_nfl(e.c)
            self.assertFalse(r["failures"], r["failures"])
            row = e.c.execute("SELECT * FROM core_nflverse_injuries WHERE gsis_id = '00-1'").fetchone()
            self.assertEqual((row["report_status"], row["report_primary_injury"], row["practice_status"]), ("Out", "Knee", DNP))
            self.assertIsNone(e.c.execute("SELECT report_status FROM core_nflverse_injuries WHERE gsis_id = '00-2'").fetchone()[0])  # '' -> NULL

    def test_unknown_status_stops_the_load(self):
        with Env() as e:
            put_nfl([{"week": 3, "gsis_id": "00-1", "report_status": "Probable"}])
            r = fw.load(e.c, get("nflverse.injuries"), fw.Scope(2026), apply=True)
            self.assertTrue(any("unknown report_status" in f for f in r["failures"]), r["failures"])
            self.assertEqual(e.c.execute("SELECT COUNT(*) FROM core_nflverse_injuries").fetchone()[0], 0)  # rolled back

    def test_playoff_weeks_may_be_small_but_regular_weeks_may_not(self):
        with Env() as e:
            with mock.patch.object(NflInjuriesLoader, "ROWS_PER_WEEK", (3, 700)):
                put_nfl([{"week": 3, "gsis_id": f"00-{i}"} for i in range(3)] + [{"week": 19, "season_type": "POST", "game_type": "WC", "gsis_id": "00-9"}])
                self.assertFalse(fw.load(e.c, get("nflverse.injuries"), fw.Scope(2026), apply=True)["failures"])
                put_nfl([{"week": 3, "gsis_id": "00-1"}])
                r = fw.load(e.c, get("nflverse.injuries"), fw.Scope(2026), apply=True)
                self.assertTrue(any("implausible row counts" in f for f in r["failures"]))

    def test_old_seasons_are_not_offered(self):
        with Env() as e:
            seasons = {s.season for s in fw.scopes(e.c, get("nflverse.injuries"))}
            self.assertTrue(seasons and min(seasons) >= 2025)   # 2016-2024 files have another header

    def test_mfl_one_row_quirk_season_from_sidecar_and_replace_whole(self):
        with Env() as e:
            put_mfl([{"id": "13589", "status": "Out", "details": "Knee", "exp_return": "Oct 11, 2026"}], week="3")
            self.assertFalse(load_mfl(e.c)["failures"])
            self.assertEqual(tuple(e.c.execute("SELECT season, week, timestamp, id, status FROM core_mfl_injuries").fetchone()),
                             (2026, 3, 1790000000, "13589", "Out"))
            put_mfl([{"id": "13592", "status": "IR", "details": "Foot", "exp_return": "x"}], week="3")
            load_mfl(e.c)
            self.assertEqual([r[0] for r in e.c.execute("SELECT id FROM core_mfl_injuries")], ["13592"])   # replaced, not appended

    def test_mfl_error_payload_is_refused(self):
        with Env() as e:
            raw.write("mfl", "injuries", "all", json.dumps({"error": "rate limited"}).encode(), "json", {"season": 2026}, 1, False)
            r = fw.load(e.c, get("mfl.injuries"), fw.Scope(0), apply=True)
            self.assertTrue(r["failures"])

    def test_both_idempotent_and_weekly(self):
        from fdb import registry
        with Env() as e:
            put_nfl([{"week": 3, "gsis_id": "00-1", "report_status": "Out"}])
            put_mfl([{"id": "1", "status": "Out", "details": "", "exp_return": ""}])
            load_feeds(e.c)
            self.assertTrue(fw.check_idempotent(e.c, get("nflverse.injuries"), fw.Scope(2026))[0])
            self.assertTrue(fw.check_idempotent(e.c, get("mfl.injuries"), fw.Scope(0))[0])
        self.assertTrue({"nflverse.injuries", "mfl.injuries"} <= set(registry.weekly_loaders()))
        self.assertEqual(registry.owner_of("app_alert_state"), "alerts.engine")


class Decide(unittest.TestCase):
    def snap(self, game=None, practice=None, mfl=None, nfl=True):
        return {"name": "Pat Back", "position": "RB", "team": "BUF", "leagues": [("Dyn", "bench")],
                "nfl": {"game": game, "practice": practice, "injury": "Knee"} if nfl else None,
                "mfl": {"status": mfl, "details": None, "exp_return": None} if mfl else None}

    def test_no_baseline_is_never_an_alert(self):
        self.assertIsNone(alerts.decide(None, None, self.snap("Out"), 3))

    def test_questionable_to_out_is_urgent(self):
        d = alerts.decide(self.snap("Questionable", "LP"), 3, self.snap("Out", "DNP"), 3)
        self.assertEqual(d["kind"], "change")
        self.assertEqual(d["changes"], [("Game", "Questionable", "Out"), ("Practice", "LP", "DNP")])
        self.assertEqual(alerts.render(self.snap("Out", "DNP"), d)["priority"], 4)

    def test_full_practice_for_a_healthy_player_is_not_news(self):
        self.assertIsNone(alerts.decide(self.snap(), 3, self.snap(practice="FP"), 3))

    def test_cleared_in_the_same_week_is_announced(self):
        d = alerts.decide(self.snap("Questionable", "LP"), 3, self.snap(None, "FP"), 3)
        self.assertEqual(d["kind"], "cleared")
        self.assertEqual(alerts.render(self.snap(None, "FP"), d)["priority"], 2)

    def test_week_roll_does_not_announce_last_weeks_designation_as_cleared(self):
        self.assertIsNone(alerts.decide(self.snap("Out", "DNP"), 3, self.snap(), 4))

    def test_week_roll_announces_a_new_designation(self):
        d = alerts.decide(self.snap(), 3, self.snap("Questionable", "LP"), 4)
        self.assertEqual(d["kind"], "change")

    def test_unpublished_report_compares_nothing_and_keeps_the_old_nfl_state(self):
        prev, cur = self.snap("Out", "DNP"), self.snap(nfl=False)
        self.assertIsNone(alerts.decide(prev, 3, cur, 4))
        self.assertEqual(alerts.carried(prev, cur)["nfl"], prev["nfl"])

    def test_mfl_status_is_compared_even_when_the_report_is_unpublished(self):
        d = alerts.decide(self.snap(nfl=False), 3, self.snap(nfl=False, mfl="IR"), 4)
        self.assertEqual(d["changes"], [("MFL", None, "IR")])

    def test_render_lists_every_league_and_both_feeds(self):
        cur = {**self.snap("Out", "DNP", mfl="Out"), "leagues": [("Elite", "roster"), ("Dyn", "starter"), ("Taxi L", "taxi")]}
        cur["mfl"].update(details="Knee - MCL", exp_return="Oct 11, 2026")
        a = alerts.render(cur, alerts.decide(self.snap("Questionable", "LP", "Questionable"), 3, cur, 3))
        self.assertEqual(a["title"], "OUT: Pat Back (RB, BUF)")
        self.assertIn("On: Elite, Dyn (starter), Taxi L (taxi)", a["body"])
        self.assertIn("MFL: Out, Knee - MCL, expected back Oct 11, 2026", a["body"])
        self.assertIn("Injury (NFL report): Knee", a["body"])


class Engine(unittest.TestCase):
    NOW = datetime(2026, 9, 26, 17, tzinfo=timezone.utc)

    def setup(self, e):
        e.person("00-1", "Pat Back", "13589", "RB")
        e.person("00-2", "Wes Receiver", "13592", "WR")
        e.person("00-3", "Healthy Guy", None, "QB")
        rost = {"00-1": {"name": "Pat Back", "position": "RB", "team": "BUF", "leagues": [("Elite", "roster"), ("Dyn", "starter")]},
                "00-2": {"name": "Wes Receiver", "position": "WR", "team": "BUF", "leagues": [("Elite", "roster")]},
                "00-3": {"name": "Healthy Guy", "position": "QB", "team": "BUF", "leagues": [("Dyn", "bench")]}}
        return mock.patch.object(alerts, "rostered", lambda conn, season: json.loads(json.dumps(rost)))

    def feeds(self, e, nfl, mfl=None):
        put_nfl(nfl)
        put_mfl(mfl or [{"id": "1", "status": "IR", "details": "", "exp_return": ""}])
        for r in load_feeds(e.c):
            self.assertFalse(r["failures"], r["failures"])

    def test_report_week_is_the_first_incomplete_week(self):
        with Env() as e:
            self.assertEqual(alerts.report_week(e.c, 2026, self.NOW), ("REG", 3))

    def test_dry_run_default_writes_nothing_and_never_sends(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send") as send:
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Out", "practice_status": DNP}])
            self.assertEqual(alerts.run(e.c, now=self.NOW), 0)
            send.assert_not_called()
            self.assertEqual(e.c.execute("SELECT COUNT(*) FROM app_alert_state").fetchone()[0], 0)

    def test_send_before_seed_is_refused(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send") as send:
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Out"}])
            self.assertEqual(alerts.run(e.c, send=True, now=self.NOW), 1)
            send.assert_not_called()

    def test_seed_then_change_then_send_once(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Questionable", "practice_status": LIMITED}])
            alerts.run(e.c, seed=True, now=self.NOW)
            self.assertEqual(e.c.execute("SELECT COUNT(*) FROM app_alert_state").fetchone()[0], 3)
            send.assert_not_called()   # seeding announces nothing
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Out", "practice_status": DNP}])
            self.assertEqual(alerts.run(e.c, send=True, now=self.NOW), 0)
            self.assertEqual(send.call_count, 1)
            title, body = send.call_args.args[:2]
            self.assertEqual(title, "OUT: Pat Back (RB, BUF)")
            self.assertIn("On: Elite, Dyn (starter)", body)   # one push for the player, every league listed
            self.assertEqual(e.c.execute("SELECT ok FROM app_alert_log").fetchall()[0][0], 1)
            alerts.run(e.c, send=True, now=self.NOW)           # same data again: announced once only
            self.assertEqual(send.call_count, 1)

    def test_failed_push_is_retried_next_run(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=False) as send:
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Questionable"}])
            alerts.run(e.c, seed=True, now=self.NOW)
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Out"}])
            self.assertEqual(alerts.run(e.c, send=True, now=self.NOW), 1)
            self.assertEqual(e.c.execute("SELECT ok FROM app_alert_log").fetchone()[0], 0)
            send.return_value = True
            alerts.run(e.c, send=True, now=self.NOW)
            self.assertEqual(send.call_count, 2)               # the same alert, sent on the retry
            alerts.run(e.c, send=True, now=self.NOW)
            self.assertEqual(send.call_count, 2)

    def test_an_unpublished_next_week_does_not_clear_anyone(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Out", "practice_status": DNP}])
            alerts.run(e.c, seed=True, now=self.NOW)
            # the clock moves to week 4's window; the file still holds only week 3 (week 4's report is not out)
            later = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
            e.c.execute("UPDATE core_schedule SET result = 1 WHERE season = 2026 AND week = 3 AND result IS NULL")  # week 3 got played
            with mock.patch.dict("os.environ", {"FDB_NOW": later.isoformat()}):
                ev = alerts.evaluate(e.c, later)
                self.assertEqual((ev.week, ev.nfl_published), (4, False))
                self.assertIsNone(ev.players["00-1"]["nfl"])
                alerts.run(e.c, send=True, now=later)
            send.assert_not_called()
            # and the stored NFL state survived, so week 4's report can still be compared against it
            self.assertEqual(json.loads(e.c.execute("SELECT snapshot_json FROM app_alert_state WHERE gsis_id='00-1'").fetchone()[0])["nfl"]["game"], "Out")

    def test_app_alert_state_survives_a_rebuild_export(self):
        from fdb import rebuild
        with Env() as e, self.setup(e):
            self.feeds(e, [{"week": 3, "gsis_id": "00-1", "report_status": "Out"}])
            alerts.run(e.c, seed=True, now=self.NOW)
            self.assertIn("app_alert_state", rebuild.export_app_state(e.c))
            self.assertTrue((config.APP_STATE_DIR / "app_alert_state.csv").exists())


class Notify(unittest.TestCase):
    def test_unset_topic_is_loud_and_sends_nothing(self):
        with mock.patch.dict("os.environ", {"NTFY_TOPIC": ""}), mock.patch.object(notify.config, "ENV_PATH", notify.config.ROOT / "no.env"), \
                mock.patch.object(notify.http, "request") as req:
            self.assertFalse(notify.send("t", "m"))
            req.assert_not_called()

    def test_non_https_server_is_refused(self):
        with mock.patch.dict("os.environ", {"NTFY_TOPIC": "abc", "NTFY_SERVER": "http://ntfy.example"}), mock.patch.object(notify.http, "request") as req:
            self.assertFalse(notify.send("t", "m"))
            req.assert_not_called()

    def test_payload_and_priority_clamp(self):
        with mock.patch.dict("os.environ", {"NTFY_TOPIC": "abc", "NTFY_SERVER": "https://ntfy.example/", "NTFY_TOKEN": "tk"}), \
                mock.patch.object(notify.http, "request", return_value=(200, {}, b"")) as req:
            self.assertTrue(notify.send("Title", "x" * 9000, priority=9, tags=("warning",)))
            url = req.call_args.args[0]
            body = json.loads(req.call_args.kwargs["data"])
            self.assertEqual(url, "https://ntfy.example")
            self.assertEqual((body["topic"], body["priority"], body["tags"]), ("abc", 5, ["warning"]))
            self.assertEqual(len(body["message"]), notify.MAX_BODY)
            self.assertEqual(req.call_args.kwargs["headers"]["Authorization"], "Bearer tk")

    def test_failure_never_echoes_the_topic(self):
        with mock.patch.dict("os.environ", {"NTFY_TOPIC": "s3cret-topic", "NTFY_SERVER": "https://ntfy.sh"}), \
                mock.patch.object(notify.http, "request", side_effect=OSError("cannot reach https://ntfy.sh/s3cret-topic")), \
                mock.patch("builtins.print") as pr:
            self.assertFalse(notify.send("t", "m"))
            self.assertNotIn("s3cret-topic", " ".join(str(c) for c in pr.call_args_list))


class EspnLoader(unittest.TestCase):
    D = "2026-09-27T15:00Z"

    def test_loads_player_id_from_the_card_link_and_flattens_details(self):
        with Env() as e:
            put_espn([espn_entry("A Back", "4429435", "BUF", "Out", self.D, fantasy="INACTIVE", comment="inactive"),
                      espn_entry("B Wideout", "99", "KC", "Active", self.D)])
            r = load_espn(e.c)
            self.assertFalse(r["failures"], r["failures"])
            row = e.c.execute("SELECT * FROM core_espn_injuries WHERE espn_player_id = '4429435'").fetchone()
            self.assertEqual((row["team"], row["status"], row["details_fantasyStatus"], row["details_type"], row["season_type"]),
                             ("BUF", "Out", "INACTIVE", "Knee", "REG"))
            self.assertIsNone(e.c.execute("SELECT details_fantasyStatus FROM core_espn_injuries WHERE espn_player_id = '99'").fetchone()[0])

    def test_entry_with_no_id_or_two_ids_refuses_the_payload(self):
        with Env() as e:
            a = espn_entry("No Id", "1", "BUF", "Out", self.D)
            a["athlete"]["links"] = [{"href": "https://www.espn.com/nfl/team/x"}]
            put_espn([a])
            self.assertTrue(any("yields 0 player ids" in f for f in load_espn(e.c)["failures"]))
            b = espn_entry("Two Ids", "1", "BUF", "Out", self.D)
            b["athlete"]["links"][1]["href"] = "https://www.espn.com/nfl/player/_/id/2/x"
            put_espn([b])
            self.assertTrue(any("yields 2 player ids" in f for f in load_espn(e.c)["failures"]))

    def test_preseason_feed_is_never_loaded(self):
        with Env() as e:
            put_espn([espn_entry("A", "1", "BUF", "Out", self.D)], season_type=1)
            self.assertTrue(any("only regular season and postseason" in f for f in load_espn(e.c)["failures"]))

    def test_unmapped_team_stops_the_load_and_replace_is_whole(self):
        with Env() as e:
            put_espn([espn_entry("A", "1", "ZZZ", "Out", self.D)])
            self.assertTrue(any("no team_aliases row" in f for f in load_espn(e.c)["failures"]))
            put_espn([espn_entry("A", "1", "BUF", "Out", self.D)])
            self.assertFalse(load_espn(e.c)["failures"])
            put_espn([espn_entry("B", "2", "KC", "Out", self.D)])
            load_espn(e.c)
            self.assertEqual([r[0] for r in e.c.execute("SELECT espn_player_id FROM core_espn_injuries")], ["2"])

    def test_fetch_gunzips_and_asks_for_gzip(self):
        body = json.dumps(espn_payload([espn_entry("A", "1", "BUF", "Out", self.D)])).encode()
        with mock.patch.object(http, "get", return_value=gzip.compress(body)) as g:
            payload, params = EspnInjuriesLoader().fetch("all")
        self.assertEqual(payload, body)
        self.assertEqual(g.call_args.kwargs["headers"], {"Accept-Encoding": "gzip"})

    def test_idempotent_and_in_the_weekly_job(self):
        from fdb import registry
        with Env() as e:
            put_espn([espn_entry("A", "1", "BUF", "Out", self.D, fantasy="OUT")])
            load_espn(e.c)
            self.assertTrue(fw.check_idempotent(e.c, get("espn.injuries"), fw.Scope(0))[0])
        self.assertIn("espn.injuries", registry.weekly_loaders())
        self.assertEqual(registry.owner_of("app_alert_final"), "alerts.engine")


class Windows(unittest.TestCase):
    def test_window_opens_two_hours_before_and_closes_at_kickoff(self):
        with Env() as e:
            gs = gameday.games(e.c, 2026, "REG", 3)
            g = gs[len(gs) // 2]
            self.assertFalse(gameday.is_open(g, g.kickoff - timedelta(minutes=121)))
            self.assertTrue(gameday.is_open(g, g.kickoff - timedelta(minutes=120)))
            self.assertTrue(gameday.is_open(g, g.kickoff - timedelta(seconds=1)))
            self.assertFalse(gameday.is_open(g, g.kickoff))
            t = g.kickoff - timedelta(hours=5)
            self.assertEqual(gameday.next_open(gs, t), min(x.kickoff - gameday.LEAD for x in gs if x.kickoff - gameday.LEAD > t))
            self.assertIsNone(gameday.next_open(gs, max(x.kickoff for x in gs)))

    def test_team_names_meet_across_espn_and_nflverse_spellings(self):
        with Env() as e:
            canon = alerts._canon(e.c, 2026)
            self.assertEqual((canon["WSH"], canon["WAS"], canon["LAR"], canon["LA"]), ("WAS", "WAS", "LA", "LA"))

    def test_when_wording(self):
        g = gameday.Game("x", "REG", 3, datetime(2026, 9, 27, 20, 25, tzinfo=timezone.utc), "16:25", "SEA", "LAC")
        self.assertEqual(g.when("SEA"), "4:25 PM ET vs LAC")
        self.assertEqual(g.when("LAC"), "4:25 PM ET @ SEA")
        self.assertEqual(gameday.Game("x", "REG", 3, g.kickoff, "09:30", "A", "B").when("A"), "9:30 AM ET vs B")
        self.assertEqual(gameday.Game("x", "REG", 3, g.kickoff, "12:00", "A", "B").when("A"), "12:00 PM ET vs B")


class GameDay(unittest.TestCase):
    """ESPN's word on game day, and what the engine does with it."""

    def espn(self, status, fantasy=None, gameday_=True, comment=None):
        return {"status": status, "fantasy": fantasy, "date": "d", "comment": comment, "injury": None, "gameday": gameday_}

    def snap(self, espn=None, game=None, nfl_game=None):
        return {"name": "Pat Back", "position": "RB", "team": "BUF", "leagues": [("Dyn", "starter")],
                "game": {"game_id": "g1", "kickoff": "2026-09-27T17:00:00+00:00", "when": "1:00 PM ET vs KC", "team": "BUF"},
                "nfl": {"game": nfl_game, "practice": None, "injury": "Knee"} if nfl_game else {"game": None, "practice": None, "injury": None},
                "mfl": None, "espn": espn}

    def test_espn_state_words(self):
        self.assertEqual(alerts.espn_state(self.espn("Active")), "ACTIVE")
        self.assertEqual(alerts.espn_state(self.espn("Out", "INACTIVE")), "INACTIVE")
        self.assertEqual(alerts.espn_state(self.espn("Out", "INACTIVE", gameday_=False)), "OUT")   # Friday's Out is not the inactive list
        self.assertIsNone(alerts.espn_state(self.espn("Active", gameday_=False)))
        self.assertEqual(alerts.espn_state(self.espn("Questionable", "QUESTIONABLE")), "QUESTIONABLE")
        self.assertIsNone(alerts.espn_state(None))

    def test_unexpected_inactive_is_the_loudest_push(self):
        prev = self.snap(self.espn("Questionable", gameday_=False), nfl_game="Questionable")
        cur = self.snap(self.espn("Out", "INACTIVE"), nfl_game="Questionable")
        d = alerts.decide(prev, 3, cur, 3)
        self.assertEqual((d["kind"], d["expected"]), ("inactive", False))
        a = alerts.render(cur, d, datetime(2026, 9, 27, 15, 40, tzinfo=timezone.utc))
        self.assertEqual((a["title"], a["priority"]), ("INACTIVE - NOT EXPECTED: Pat Back (RB, BUF)", 5))
        self.assertIn("Kickoff: 1:00 PM ET vs KC (in 80 min)", a["body"])

    def test_inactive_of_a_player_already_ruled_out_is_a_quiet_confirmation(self):
        prev = self.snap(self.espn("Out", "OUT", gameday_=False), nfl_game="Out")
        d = alerts.decide(prev, 3, self.snap(self.espn("Out", "INACTIVE"), nfl_game="Out"), 3)
        self.assertTrue(d["expected"])
        a = alerts.render(self.snap(self.espn("Out", "INACTIVE"), nfl_game="Out"), d)
        self.assertEqual((a["title"], a["priority"]), ("INACTIVE (as expected): Pat Back (RB, BUF)", 3))

    def test_coaches_decision_scratch_of_a_never_flagged_player_is_announced(self):
        d = alerts.decide(self.snap(self.espn(None)), 3, self.snap(self.espn("Out", "INACTIVE")), 3)
        self.assertEqual((d["kind"], d["expected"]), ("inactive", False))

    def test_questionable_turning_active_is_good_news(self):
        d = alerts.decide(self.snap(self.espn("Questionable", gameday_=False), nfl_game="Questionable"), 3,
                          self.snap(self.espn("Active"), nfl_game="Questionable"), 3)
        self.assertEqual(d["kind"], "active")
        self.assertEqual(alerts.render(self.snap(self.espn("Active")), d)["priority"], 4)

    def test_healthy_player_turning_active_is_not_news(self):
        self.assertIsNone(alerts.decide(self.snap(self.espn(None)), 3, self.snap(self.espn("Active")), 3))

    def test_week_roll_does_not_announce_last_weeks_inactive_as_cleared(self):
        self.assertIsNone(alerts.decide(self.snap(self.espn("Out", "INACTIVE")), 3, self.snap(self.espn(None)), 4))

    def test_unloaded_espn_compares_nothing_and_keeps_the_old_part(self):
        prev, cur = self.snap(self.espn("Out", "INACTIVE")), self.snap(espn=None)
        self.assertIsNone(alerts.decide(prev, 3, cur, 3))
        self.assertEqual(alerts.carried(prev, cur)["espn"], prev["espn"])

    def test_old_state_without_an_espn_part_still_compares(self):
        prev = self.snap(nfl_game="Questionable")
        del prev["espn"]
        d = alerts.decide(prev, 3, self.snap(self.espn("Out", "INACTIVE"), nfl_game="Questionable"), 3)
        self.assertEqual(d["kind"], "inactive")


class Engine13(unittest.TestCase):
    """End to end on the temp database: evaluate -> final check -> ledger -> watch loop under a fake clock."""
    base = Engine

    def setup(self, e):
        gs = gameday.games(e.c, 2026, "REG", 3)
        self.g = gs[len(gs) // 2]
        self.ko, self.team = self.g.kickoff, self.g.home
        e.person("00-1", "Pat Back", "13589", "RB", self.team, espn_id="1001")
        e.person("00-2", "Wes Receiver", "13592", "WR", self.team, espn_id="1002")
        e.person("00-3", "Settled Guy", None, "QB", self.team, espn_id="1003")
        rost = {g: {"name": n, "position": p, "team": self.team, "leagues": [("Elite", "roster"), ("Dyn", "starter")]}
                for g, n, p in (("00-1", "Pat Back", "RB"), ("00-2", "Wes Receiver", "WR"), ("00-3", "Settled Guy", "QB"))}
        return mock.patch.object(alerts, "rostered", lambda conn, season: json.loads(json.dumps(rost)))

    def at(self, minutes):
        return self.ko + timedelta(minutes=minutes)

    def feeds(self, e, espn, nfl=None):
        put_nfl(nfl or [{"week": 3, "gsis_id": "00-1", "report_status": "Questionable", "practice_status": LIMITED,
                         "team": self.team}, {"week": 3, "gsis_id": "00-2", "report_status": "Questionable", "team": self.team}])
        put_mfl([{"id": "1", "status": "IR", "details": "", "exp_return": ""}])
        put_espn(espn)
        for r in (load_nfl(e.c), load_mfl(e.c), load_espn(e.c)):
            self.assertFalse(r["failures"], r["failures"])

    def test_evaluate_marks_gameday_entries_and_counts_what_espn_posted(self):
        with Env() as e, self.setup(e):
            early = iso(self.at(-60 * 30))   # a day and a half before
            late = iso(self.at(-80))
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", early, fantasy="QUESTIONABLE"),
                           espn_entry("Settled Guy", "1003", self.team, "Active", late, comment="is active for Sunday")])
            ev = alerts.evaluate(e.c, self.at(-70))
            self.assertFalse(ev.players["00-1"]["espn"]["gameday"])
            self.assertTrue(ev.players["00-3"]["espn"]["gameday"])
            self.assertEqual(alerts.espn_state(ev.players["00-3"]["espn"]), "ACTIVE")
            self.assertEqual(ev.posted, {self.team: 1})
            self.assertEqual(ev.players["00-1"]["game"]["game_id"], self.g.game_id)

    def test_final_check_once_only_for_the_still_uncertain(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE"),
                           espn_entry("Settled Guy", "1003", self.team, "Active", iso(self.at(-80)))])
            alerts.run(e.c, seed=True, now=self.at(-70))
            for t, expect in ((-30, 0), (-15, 2), (-14, 0), (-1, 0)):
                with self.subTest(minutes_before=-t):
                    n0 = send.call_count
                    alerts.run(e.c, send=True, now=self.at(t))
                    self.assertEqual(send.call_count - n0, expect)
            titles = sorted(c.args[0] for c in send.call_args_list)
            self.assertEqual(titles, ["NOT CONFIRMED: Pat Back (RB, " + self.team + ")", "NOT CONFIRMED: Wes Receiver (WR, " + self.team + ")"])
            body = {c.args[0]: c.args[1] for c in send.call_args_list}["NOT CONFIRMED: Wes Receiver (WR, " + self.team + ")"]
            self.assertIn("Kickoff in 15 min", body)
            self.assertNotIn("WARNING", body)   # ESPN did post game-day entries for his team (Settled Guy's)
            self.assertEqual(e.c.execute("SELECT COUNT(*) FROM app_alert_final WHERE ok = 1").fetchone()[0], 2)

    def test_final_check_says_so_when_espn_has_posted_nothing_for_the_team(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            # his only ESPN entry is from a day and a half earlier: nothing game-day was posted for his team
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE")])
            alerts.run(e.c, seed=True, now=self.at(-70))
            alerts.run(e.c, send=True, now=self.at(-15))
            body = next(c.args[1] for c in send.call_args_list if "Pat Back" in c.args[0])
            self.assertIn(f"ESPN has posted NO game-day entries for {self.team}", body)

    def test_failed_final_check_is_retried_until_kickoff(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=False) as send:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE")])
            alerts.run(e.c, seed=True, now=self.at(-70))
            self.assertEqual(alerts.run(e.c, send=True, now=self.at(-15)), 1)
            self.assertEqual(e.c.execute("SELECT ok FROM app_alert_final").fetchone()[0], 0)
            send.return_value = True
            alerts.run(e.c, send=True, now=self.at(-10))
            self.assertEqual(e.c.execute("SELECT ok FROM app_alert_final WHERE gsis_id = '00-1'").fetchone()[0], 1)
            n = send.call_count
            alerts.run(e.c, send=True, now=self.at(-5))
            self.assertEqual(send.call_count, n)

    def test_started_game_and_already_out_player_get_no_final_check(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE")],
                       nfl=[{"week": 3, "gsis_id": "00-1", "report_status": "Out", "team": self.team}])
            alerts.run(e.c, seed=True, now=self.at(-70))
            alerts.run(e.c, send=True, now=self.at(-15))   # Out per the NFL report, ESPN still says Questionable: uncertain -> checked
            self.assertEqual(send.call_count, 1)
            alerts.run(e.c, send=True, now=self.at(5))     # kicked off
            self.assertEqual(send.call_count, 1)

    def test_watch_refuses_to_send_without_a_baseline(self):
        with Env() as e, self.setup(e), mock.patch.object(alerts, "refresh") as rf:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)))])
            self.assertEqual(alerts.watch(e.c, send=True, now_fn=lambda: self.at(-100), sleep=lambda s: None), 1)
            rf.assert_not_called()

    def test_watch_polls_only_inside_the_window_pushes_the_inactive_and_the_final_check_and_exits(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE"),
                           espn_entry("Wes Receiver", "1002", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE")])
            alerts.run(e.c, seed=True, now=self.at(-200))
            clock, sleeps, polls = [self.at(-130)], [], []

            def fake_sleep(s):
                sleeps.append(s)
                clock[0] += timedelta(seconds=s)

            def fake_refresh(conn, loaders=()):
                polls.append((clock[0], tuple(loaders)))
                if len(polls) == 3:   # ESPN posts Pat Back as a surprise inactive on the third poll
                    put_espn([espn_entry("Pat Back", "1001", self.team, "Out", iso(clock[0] - timedelta(minutes=1)), fantasy="INACTIVE"),
                              espn_entry("Wes Receiver", "1002", self.team, "Questionable", iso(self.at(-60 * 30)), fantasy="QUESTIONABLE")])
                    load_espn(e.c)
                return []

            with mock.patch.object(alerts, "refresh", fake_refresh):
                rc = alerts.watch(e.c, send=True, poll_s=120, horizon_h=2, now_fn=lambda: clock[0], sleep=fake_sleep)
            self.assertEqual(rc, 0)
            gs = gameday.games(e.c, 2026, "REG", 3)   # other games of the slate open their own windows after this one's
            self.assertTrue(all(any(gameday.is_open(g, t) for g in gs) for t, _ in polls), "polled outside every kickoff window")
            self.assertTrue(all(b[0] - a[0] >= timedelta(seconds=120) for a, b in zip(polls, polls[1:])), "polled faster than every 120 s")
            self.assertGreater(polls[0][0], self.at(-125))   # nothing before the window opened (sleeps were chunked to <= 300 s)
            self.assertEqual(polls[0][1], ("espn.injuries", "nflverse.injuries", "mfl.injuries"))   # the first poll refreshes everything
            self.assertEqual(polls[1][1], ("espn.injuries",))
            titles = [c.args[0] for c in send.call_args_list]
            self.assertEqual(titles.count("INACTIVE - NOT EXPECTED: Pat Back (RB, " + self.team + ")"), 1)
            self.assertEqual(titles.count("NOT CONFIRMED: Wes Receiver (WR, " + self.team + ")"), 1)
            self.assertFalse(any("Pat Back" in t and "NOT CONFIRMED" in t for t in titles))   # settled by the inactive

    def test_watch_exits_at_once_when_no_window_is_near(self):
        with Env() as e, self.setup(e), mock.patch.object(alerts, "refresh") as rf:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)))])
            alerts.run(e.c, seed=True, now=self.at(-200))
            slept = []
            rc = alerts.watch(e.c, send=True, horizon_h=3, now_fn=lambda: self.at(-60 * 20), sleep=slept.append)
            self.assertEqual((rc, slept), (0, []))
            rf.assert_not_called()

    def test_a_second_watcher_refuses_to_start(self):
        with Env() as e:
            with alerts._lock():
                with self.assertRaises(SystemExit):
                    with alerts._lock():
                        pass
            with alerts._lock():   # released afterwards
                pass

    def test_three_failed_espn_polls_in_a_window_push_one_warning(self):
        with Env() as e, self.setup(e), mock.patch.object(notify, "send", return_value=True) as send:
            self.feeds(e, [espn_entry("Pat Back", "1001", self.team, "Questionable", iso(self.at(-60 * 30)))])
            alerts.run(e.c, seed=True, now=self.at(-200))
            clock = [self.at(-100)]
            with mock.patch.object(alerts, "refresh", lambda conn, loaders=(): ["espn.injuries: URLError: down"]):
                alerts.watch(e.c, send=True, poll_s=120, horizon_h=2, now_fn=lambda: clock[0],
                             sleep=lambda s: clock.__setitem__(0, clock[0] + timedelta(seconds=s)), max_polls=6)
            self.assertEqual([c.args[0] for c in send.call_args_list if c.args[0].startswith("ALERTS:")], ["ALERTS: ESPN feed failing"])


if __name__ == "__main__":
    unittest.main()
