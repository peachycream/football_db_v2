"""Phase 11: `fdb post` (fdb/discord_post.py): manual, 30590 only, once per league-week-mode. Offline: a LOCAL fake webhook server
stands in for Discord, the renderer is mocked, and nothing here can reach the real service."""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from fdb import card_render, config, discord_post as dp, rebuild
from tests.test_matchup_card import AFTER_KICKOFF, BEFORE_KICKOFF, L, MartEnv

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-card-pixels" * 100
TOKEN = "SECRETtokenSECRETtoken123"


class Fake:
    """A local webhook endpoint. `script` is a list of (status, json body) answers; the last repeats."""

    def __init__(self, script=None):
        self.requests, self.script = [], list(script or [(200, {"id": "111222333"})])
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "ctype": self.headers.get("Content-Type", ""), "body": body})
                status, obj = outer.script.pop(0) if len(outer.script) > 1 else outer.script[0]
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/webhooks/123456/{TOKEN}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Post(MartEnv):
    """MartEnv with the poster pointed at league 11111, a fake webhook, a mocked renderer and a good weekly status."""

    def __enter__(self):
        super().__enter__()
        self.fake = Fake()
        self.cards = Path(tempfile.mkdtemp(prefix="fdb_post_"))
        self.patches2 = [
            mock.patch.object(dp, "LEAGUES", (L,)),
            mock.patch.object(dp, "WEBHOOK_RE", __import__("re").compile(r"^http://127\.0\.0\.1:\d+/api/webhooks/\d+/[A-Za-z0-9_\-]+$")),
            mock.patch.object(dp, "weekly_status", return_value=(True, "")),
            mock.patch.object(dp.time, "sleep"),
            mock.patch.object(card_render, "CARDS_DIR", self.cards),
            mock.patch.object(card_render, "render_png", return_value=FAKE_PNG),
            mock.patch.dict(os.environ, {dp.ENV_PREFIX + L: self.fake.url}),
        ]
        for p in self.patches2:
            p.start()
        self.seed_all()
        self.c.execute("PRAGMA foreign_keys = ON")
        return self

    def __exit__(self, *exc):
        for p in self.patches2:
            p.stop()
        self.fake.close()
        return super().__exit__(*exc)

    def post(self, mode="recap", now=AFTER_KICKOFF, **kw):
        self.build(now=now)
        self.c.commit()
        buf = io.StringIO()
        kw.setdefault("send_it", False)
        with contextlib.redirect_stdout(buf), mock.patch.dict(os.environ, {"FDB_NOW": now}):
            rc = dp.run(self.c, mode, L, **kw)
        return rc, buf.getvalue()

    def rows(self):
        return [tuple(r) for r in self.c.execute("SELECT league_id, season, week, mode, status, message_id FROM app_post_log")]


class Webhook(unittest.TestCase):
    def test_only_real_discord_webhook_urls_are_valid(self):
        good = ["https://discord.com/api/webhooks/123456789/abcDEF_-123", "https://discordapp.com/api/webhooks/1/a",
                "https://ptb.discord.com/api/webhooks/1/a", "https://canary.discord.com/api/webhooks/1/a"]
        bad = ["", "http://discord.com/api/webhooks/1/a", "https://example.com/api/webhooks/1/a", "https://discord.com.evil.io/api/webhooks/1/a",
               "https://discord.com/api/webhooks/1/a/extra", "https://discord.com/api/webhooks/x/a", "<paste webhook here>",
               "javascript:alert(1)", "https://discord.com/api/webhooks/1/a?x=1"]
        for u in good:
            self.assertTrue(dp.valid_webhook(u), u)
        for u in bad:
            self.assertFalse(dp.valid_webhook(u), u)

    def test_redact_removes_the_url_and_the_token(self):
        url = f"https://discord.com/api/webhooks/1/{TOKEN}"
        out = dp.redact(f"boom {url} and {TOKEN} again", url)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn("discord.com/api", out)

    def test_multipart_has_one_payload_with_no_mentions_and_one_png(self):
        body, ctype = dp.multipart({"content": "hi", "allowed_mentions": {"parse": []}}, "c.png", FAKE_PNG)
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="payload_json"', body)
        self.assertIn(b'name="files[0]"; filename="c.png"', body)
        self.assertIn(FAKE_PNG, body)
        self.assertIn(b'"allowed_mentions": {"parse": []}', body)


class DryRun(unittest.TestCase):
    def test_dry_run_renders_and_reports_but_sends_and_logs_nothing(self):
        with Post() as env:
            rc, out = env.post("recap")
            self.assertEqual(rc, 0, out)
            self.assertIn("DRY RUN. Nothing was sent", out)
            self.assertIn("week 2", out)
            self.assertEqual(env.fake.requests, [])
            self.assertEqual(env.rows(), [])
            self.assertEqual(len(list(env.cards.glob("*.png"))), 1)   # the exact bytes that would be sent are on disk

    def test_dry_run_works_with_no_webhook_at_all(self):
        with Post() as env:
            with mock.patch.dict(os.environ, {dp.ENV_PREFIX + L: ""}):
                with mock.patch.object(config, "ENV_PATH", Path(tempfile.mkdtemp()) / "none.env"):
                    rc, out = env.post("recap")
            self.assertEqual(rc, 0, out)
            self.assertIn("webhook: not set", out)

    def test_the_summary_never_shows_the_webhook(self):
        with Post() as env:
            rc, out = env.post("recap")
            self.assertNotIn(TOKEN, out)
            self.assertNotIn(env.fake.url, out)


class Sending(unittest.TestCase):
    def test_send_posts_one_message_with_one_image_and_logs_it(self):
        with Post() as env:
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 0, out)
            self.assertIn("POSTED", out)
            self.assertEqual(len(env.fake.requests), 1)
            r = env.fake.requests[0]
            self.assertIn("wait=true", r["path"])
            self.assertIn(b'"allowed_mentions": {"parse": []}', r["body"])        # can never ping anyone
            self.assertIn(b"Week 2 recap", r["body"])
            self.assertIn(FAKE_PNG, r["body"])
            self.assertEqual(env.rows(), [(L, 2026, 2, "recap", "posted", "111222333")])
            row = env.c.execute("SELECT png_sha256, posted_at FROM app_post_log").fetchone()
            self.assertEqual(len(row[0]), 64)
            self.assertTrue(row[1].endswith("Z"))
            self.assertNotIn(TOKEN, out)

    def test_the_same_week_is_never_posted_twice(self):
        with Post() as env:
            self.assertEqual(env.post("recap", send_it=True, yes=True)[0], 0)
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("already posted", out)
            self.assertEqual(len(env.fake.requests), 1)

    def test_repost_is_the_one_deliberate_override(self):
        with Post() as env:
            env.post("recap", send_it=True, yes=True)
            rc, out = env.post("recap", send_it=True, yes=True, repost=True)
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(env.fake.requests), 2)
            self.assertEqual(env.c.execute("SELECT detail FROM app_post_log").fetchone()[0], "HTTP 200")   # row rewritten, one row

    def test_a_recap_and_a_preview_are_separate_posts(self):
        with Post() as env:
            self.assertEqual(env.post("recap", now=BEFORE_KICKOFF, send_it=True, yes=True)[0], 0)
            self.assertEqual(env.post("preview", now=BEFORE_KICKOFF, send_it=True, yes=True)[0], 0)
            self.assertEqual({r[3] for r in env.rows()}, {"recap", "preview"})
            self.assertEqual(len(env.fake.requests), 2)

    def test_a_failed_send_is_logged_failed_and_retried_without_any_flag(self):
        with Post() as env:
            env.fake.script[:] = [(500, {"message": "boom"}), (200, {"id": "42"})]
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("FAILED", out)
            self.assertEqual(env.rows(), [(L, 2026, 2, "recap", "failed", None)])
            self.assertNotIn(TOKEN, out)
            self.assertNotIn(TOKEN, env.c.execute("SELECT detail FROM app_post_log").fetchone()[0])
            rc, out = env.post("recap", send_it=True, yes=True)           # no --repost needed
            self.assertEqual(rc, 0, out)
            self.assertEqual(env.rows(), [(L, 2026, 2, "recap", "posted", "42")])

    def test_rate_limit_waits_the_time_discord_names_then_posts_once(self):
        with Post() as env:
            env.fake.script[:] = [(429, {"retry_after": 2.5}), (200, {"id": "7"})]
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(env.fake.requests), 2)
            dp.time.sleep.assert_any_call(2.5)
            self.assertEqual(env.rows()[0][4], "posted")

    def test_endless_rate_limiting_ends_as_a_failure(self):
        with Post() as env:
            env.fake.script[:] = [(429, {"retry_after": 0.1})]
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertEqual(env.rows()[0][4], "failed")
            self.assertEqual(len(env.fake.requests), dp.MAX_429_RETRIES + 1)

    def test_an_unfinished_attempt_blocks_until_a_human_says_otherwise(self):
        with Post() as env:
            env.c.execute("INSERT INTO app_post_log (league_id, season, week, mode, status, claimed_at) VALUES (?, 2026, 2, 'recap', 'sending', '2026-10-04T12:00:00Z')", (L,))
            env.c.commit()
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("MAY have been delivered", out)
            self.assertEqual(env.fake.requests, [])
            rc, out = env.post("recap", send_it=True, yes=True, repost=True)
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(env.fake.requests), 1)

    def test_the_claim_is_made_before_the_request(self):
        with Post() as env:
            seen = []
            real = dp.send

            def spy(*a, **k):
                seen.append(env.c.execute("SELECT status FROM app_post_log").fetchone()[0])
                return real(*a, **k)
            with mock.patch.object(dp, "send", spy):
                env.post("recap", send_it=True, yes=True)
            self.assertEqual(seen, ["sending"])


class Refusals(unittest.TestCase):
    def test_no_webhook_means_no_send_and_no_claim(self):
        with Post() as env:
            with mock.patch.dict(os.environ, {dp.ENV_PREFIX + L: ""}), mock.patch.object(config, "ENV_PATH", Path(tempfile.mkdtemp()) / "none.env"):
                rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("is not set in .env", out)
            self.assertEqual(env.rows(), [])

    def test_a_placeholder_webhook_is_refused(self):
        with Post() as env:
            with mock.patch.dict(os.environ, {dp.ENV_PREFIX + L: "https://example.com/hook"}):
                rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("not a Discord webhook URL", out)
            self.assertEqual((env.fake.requests, env.rows()), ([], []))

    def test_only_the_configured_league_can_be_posted(self):
        with Post() as env:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = dp.run(env.c, "recap", "60398", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("enabled for league", buf.getvalue())
            self.assertEqual(env.fake.requests, [])

    def test_a_preview_after_kickoff_is_refused_and_no_week_is_substituted(self):
        with Post() as env:
            rc, out = env.post("preview", now=AFTER_KICKOFF, send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("already kicked off", out)
            self.assertEqual((env.fake.requests, env.rows()), ([], []))

    def test_a_preview_without_a_projection_needs_an_explicit_flag(self):
        with Post() as env:
            env.c.execute("DELETE FROM core_mfl_projected_scores")
            env.c.commit()
            rc, out = env.post("preview", now=BEFORE_KICKOFF, send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("--allow-no-projection", out)
            self.assertEqual(env.fake.requests, [])
            rc, out = env.post("preview", now=BEFORE_KICKOFF, send_it=True, yes=True, allow_no_projection=True)
            self.assertEqual(rc, 0, out)

    def test_nothing_ready_means_nothing_sent(self):
        with Post() as env:
            env.c.execute("DELETE FROM core_mfl_weekly_results")
            env.c.commit()
            rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("not ready", out)
            self.assertEqual(env.fake.requests, [])

    def test_a_failed_or_stale_weekly_run_blocks_unless_overridden(self):
        with Post() as env:
            with mock.patch.object(dp, "weekly_status", return_value=(False, "the last weekly run is 'failed', not ok")):
                rc, out = env.post("recap", send_it=True, yes=True)
                self.assertEqual(rc, 1)
                self.assertIn("--ignore-weekly-status", out)
                self.assertEqual(env.fake.requests, [])
                rc, out = env.post("recap", send_it=True, yes=True, ignore_weekly_status=True)
                self.assertEqual(rc, 0, out)

    def test_render_failure_sends_nothing(self):
        with Post() as env:
            with mock.patch.object(card_render, "render_png", side_effect=card_render.RenderError("no browser")):
                rc, out = env.post("recap", send_it=True, yes=True)
            self.assertEqual(rc, 1)
            self.assertIn("could not render", out)
            self.assertEqual((env.fake.requests, env.rows()), ([], []))


class Confirmation(unittest.TestCase):
    def test_send_without_a_terminal_and_without_yes_is_refused(self):
        notty = mock.Mock()
        notty.isatty.return_value = False
        with Post() as env:
            with mock.patch.object(sys, "stdin", notty):
                rc, out = env.post("recap", send_it=True)
            self.assertEqual(rc, 1)
            self.assertIn("pass --yes", out)
            self.assertEqual((env.fake.requests, env.rows()), ([], []))

    def test_a_terminal_that_cannot_be_read_is_refused_not_a_crash(self):
        tty = mock.Mock()
        tty.isatty.return_value = True
        with Post() as env:
            with mock.patch.object(sys, "stdin", tty):
                rc, out = env.post("recap", send_it=True, ask=mock.Mock(side_effect=EOFError))
            self.assertEqual(rc, 1)
            self.assertIn("cannot be read", out)
            self.assertEqual((env.fake.requests, env.rows()), ([], []))

    def test_at_a_terminal_only_the_word_yes_posts(self):
        tty = mock.Mock()
        tty.isatty.return_value = True
        with Post() as env:
            with mock.patch.object(sys, "stdin", tty):
                rc, out = env.post("recap", send_it=True, ask=lambda p: "y")
                self.assertEqual(rc, 1)
                self.assertIn("cancelled", out)
                self.assertEqual((env.fake.requests, env.rows()), ([], []))
                rc, out = env.post("recap", send_it=True, ask=lambda p: "yes")
                self.assertEqual(rc, 0, out)
            self.assertEqual(len(env.fake.requests), 1)


class WeeklyStatus(unittest.TestCase):
    def write(self, **kw):
        p = Path(tempfile.mkdtemp()) / "PIPELINE_STATUS.json"
        p.write_text(json.dumps(kw), encoding="utf-8")
        return mock.patch.object(config, "STATUS_PATH", p)

    def test_ok_and_recent_passes(self):
        now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        with self.write(state="ok", finished_at=(now - timedelta(days=2)).isoformat()):
            self.assertEqual(dp.weekly_status(now), (True, ""))

    def test_failed_stale_missing_and_odd_files_block(self):
        now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        with self.write(state="failed", finished_at=now.isoformat()):
            self.assertFalse(dp.weekly_status(now)[0])
        with self.write(state="ok", finished_at=(now - timedelta(days=12)).isoformat()):
            ok, why = dp.weekly_status(now)
            self.assertFalse(ok)
            self.assertIn("12 days ago", why)
        with self.write(state="ok"):
            self.assertFalse(dp.weekly_status(now)[0])
        with mock.patch.object(config, "STATUS_PATH", Path(tempfile.mkdtemp()) / "missing.json"):
            self.assertFalse(dp.weekly_status(now)[0])


class Persistence(unittest.TestCase):
    def test_the_post_log_is_exported_across_rebuilds(self):
        with Post() as env:
            env.post("recap", send_it=True, yes=True)
            with mock.patch.object(config, "APP_STATE_DIR", Path(tempfile.mkdtemp(prefix="fdb_state_"))):
                self.assertIn("app_post_log", rebuild.export_app_state(env.c))
                csv_text = (config.APP_STATE_DIR / "app_post_log.csv").read_text(encoding="utf-8")
                self.assertIn("posted", csv_text)
                self.assertIn("111222333", csv_text)


if __name__ == "__main__":
    unittest.main()
