"""Phase 12: injury-feed loaders, the alert engine's decisions, its state, and the ntfy sender.
Offline: feeds are fixtures in the raw store; the network is never touched (notify's http is mocked)."""
import csv
import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fdb import alerts, config, loader as fw, notify, raw
from fdb.loaders import get
from fdb.loaders.injuries import MflInjuriesLoader, NflInjuriesLoader
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
                         mock.patch.object(MflInjuriesLoader, "ROWS", (1, 3000))]
        for p in self.patches2:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches2:
            p.stop()
        return super().__exit__(*exc)

    def person(self, gsis, name, mfl_id=None, pos="WR", team="BUF"):
        self.c.execute("INSERT INTO players (gsis_id, display_name, position, latest_team, players_source) VALUES (?,?,?,?, 'rosters_weekly')",
                       (gsis, name, pos, team))
        if mfl_id:
            self.c.execute("INSERT INTO player_ids (source, source_id, gsis_id, method, evidence) VALUES ('mfl',?,?,'id_map','test')",
                           (mfl_id, gsis))


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


if __name__ == "__main__":
    unittest.main()
