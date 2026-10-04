"""Phase 11: the PNG renderer (fdb/card_render.py), `fdb card`, and /matchup/card.png. Offline: logo downloads are mocked;
one test drives the real headless Chromium (skipped where Playwright or its browser is missing). Nothing here posts."""
import base64
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fdb import card_render as cr
from fdb import http
from fdb import matchup_card as mc
from tests.test_matchup_card import AFTER_KICKOFF, L, MartEnv

PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def png_size(data: bytes):
    return struct.unpack(">II", data[16:24])


class LogoCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fdb_logos_")
        self.p = mock.patch.object(cr, "LOGO_DIR", Path(self.dir))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_png_is_embedded_and_cached_after_one_download(self):
        with mock.patch.object(http, "get", return_value=PNG_1PX) as get:
            a = cr.fetch_logo("https://img.example/a.png")
            b = cr.fetch_logo("https://img.example/a.png")
        self.assertTrue(a.startswith("data:image/png;base64,"))
        self.assertEqual(a, b)
        self.assertEqual(get.call_count, 1)

    def test_content_is_sniffed_not_trusted(self):
        with mock.patch.object(http, "get", return_value=b"<html><script>alert(1)</script></html>"):
            self.assertIsNone(cr.fetch_logo("https://img.example/evil.png"))   # an "image" that is HTML

    def test_oversize_and_failures_give_no_logo_and_are_not_retried_at_once(self):
        with mock.patch.object(http, "get", return_value=PNG_1PX + b"0" * (cr.MAX_LOGO_BYTES + 1)):
            self.assertIsNone(cr.fetch_logo("https://img.example/big.png"))
        with mock.patch.object(http, "get", side_effect=OSError("boom")) as get:
            self.assertIsNone(cr.fetch_logo("https://img.example/down.png"))
            self.assertIsNone(cr.fetch_logo("https://img.example/down.png"))
        self.assertEqual(get.call_count, 1)   # the miss is remembered for a day

    def test_network_disabled_means_no_logo_not_a_crash(self):
        with mock.patch.object(http, "NETWORK_ENABLED", False):
            self.assertIsNone(cr.fetch_logo("https://img.example/x.png"))

    def test_only_http_urls_are_fetched(self):
        with mock.patch.object(http, "get") as get:
            for u in (None, "", "javascript:alert(1)", "file:///etc/passwd", "data:image/png;base64,AAAA"):
                self.assertIsNone(cr.fetch_logo(u))
        get.assert_not_called()

    def test_sniff(self):
        self.assertEqual(cr.sniff(PNG_1PX), "image/png")
        self.assertEqual(cr.sniff(b"\xff\xd8\xff\xe0abc"), "image/jpeg")
        self.assertEqual(cr.sniff(b"GIF89a.."), "image/gif")
        self.assertEqual(cr.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertIsNone(cr.sniff(b"<svg"))


class Html(unittest.TestCase):
    def card(self, env):
        env.seed_all()
        env.build(now=AFTER_KICKOFF)
        return mc.card(env.c, L, 2026, 1, "0001", "0002")

    def test_data_uri_logos_render_and_other_schemes_do_not(self):
        with MartEnv() as env:
            c = self.card(env)
            c["home"]["logo"] = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
            c["away"]["logo"] = "data:text/html;base64,PHNjcmlwdD4="
            h = mc.card_html(c)
            self.assertIn('src="data:image/png;base64,', h)
            self.assertNotIn("data:text/html", h)

    def test_embed_logos_replaces_urls_and_leaves_the_card_alone(self):
        with MartEnv() as env:
            c = self.card(env)
            c["home"]["logo"] = "https://img.example/h.png"
            with mock.patch.object(cr, "fetch_logo", side_effect=lambda u: "data:image/png;base64,AAAA" if u else None):
                out = cr.embed_logos(c)
            self.assertEqual(out["home"]["logo"], "data:image/png;base64,AAAA")
            self.assertIsNone(out["away"]["logo"])
            self.assertEqual(c["home"]["logo"], "https://img.example/h.png")   # the input is not mutated

    def test_standalone_document(self):
        with MartEnv() as env:
            doc = cr.standalone_html(self.card(env))
            self.assertTrue(doc.startswith("<!DOCTYPE html>"))
            self.assertIn('class="mc"', doc)
            self.assertIn("charset", doc)

    def test_filename_names_the_game_and_the_state(self):
        with MartEnv() as env:
            self.assertEqual(cr.filename(self.card(env)), f"{L}_2026_wk01_final_0002_at_0001.png")


class Failure(unittest.TestCase):
    def test_a_missing_playwright_is_a_named_error_not_a_blank_image(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            c = mc.card(env.c, L, 2026, 1, "0001", "0002")
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(cr.RenderError) as cm:
                cr.render_png(c)
        self.assertIn("playwright is not installed", str(cm.exception))

    def test_a_browser_failure_is_a_named_error(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            c = mc.card(env.c, L, 2026, 1, "0001", "0002")
        fake = mock.MagicMock()
        fake.chromium.launch.side_effect = RuntimeError("Executable doesn't exist\nrun playwright install")
        ctx = mock.MagicMock()
        ctx.__enter__.return_value = fake
        with mock.patch("playwright.sync_api.sync_playwright", return_value=ctx):
            with self.assertRaises(cr.RenderError) as cm:
                cr.render_png(c, embed=False)
        self.assertIn("headless Chromium failed", str(cm.exception))

    def test_no_data_and_no_such_game_are_named(self):
        with MartEnv() as env:
            env.c.commit()
            with self.assertRaises(cr.RenderError) as cm:
                cr.render_to_file(env.c)
            self.assertIn("no matchup data", str(cm.exception))
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            with self.assertRaises(cr.RenderError) as cm:
                cr.render_to_file(env.c, L, 2026, 1, "0001", "0003")
            self.assertIn("no such game", str(cm.exception))


def _chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_chromium_available(), "Playwright's Chromium is not installed")
class RealRender(unittest.TestCase):
    def test_png_of_a_final_card_and_the_cli_and_the_route(self):
        out_dir = Path(tempfile.mkdtemp(prefix="fdb_cards_"))
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            c = mc.card(env.c, L, 2026, 1, "0001", "0002")
            png = cr.render_png(c, embed=False)
            self.assertTrue(png.startswith(b"\x89PNG"))
            w, h = png_size(png)
            self.assertEqual(w, (680 + 2) * cr.SCALE)       # the card (680 wide plus its 1px border each side), at 2x
            self.assertGreater(h, 600 * cr.SCALE)
            # default = the newest week's FEATURED game, written to the requested folder, announced, never posted
            with mock.patch.object(cr, "CARDS_DIR", out_dir):
                path, card = cr.render_to_file(env.c)
            self.assertEqual(path.parent, out_dir)
            self.assertTrue(card["featured"])
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
            # the route returns the same kind of image, and a 404 for a game that does not exist
            from app import create_app
            app = create_app()
            app.logger.setLevel("CRITICAL")
            cl = app.test_client()
            r = cl.get(f"/matchup/card.png?league={L}&season=2026&week=1&home=0001&away=0002")
            self.assertEqual((r.status_code, r.mimetype), (200, "image/png"))
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertTrue(r.data.startswith(b"\x89PNG"))
            self.assertEqual(cl.get("/matchup/card.png?home=x&away=y").status_code, 404)

    def test_the_route_says_503_when_the_render_cannot_run(self):
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            from app import create_app
            app = create_app()
            app.logger.setLevel("CRITICAL")
            with mock.patch.object(cr, "render_png", side_effect=cr.RenderError("no browser")):
                r = app.test_client().get(f"/matchup/card.png?league={L}&season=2026&week=1&home=0001&away=0002")
            self.assertEqual(r.status_code, 503)
            self.assertIn("no browser", r.data.decode())

    def test_the_cli_prints_the_path_and_says_it_posted_nothing(self):
        out = Path(tempfile.mkdtemp(prefix="fdb_cli_")) / "c.png"
        with MartEnv() as env:
            env.seed_all()
            env.build(now=AFTER_KICKOFF)
            env.c.commit()
            from fdb import __main__ as cli
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = cli.main(["card", "--league", L, "--season", "2026", "--week", "1", "--home", "0001", "--away", "0002", "--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertIn("nothing was posted", buf.getvalue())
            self.assertTrue(out.read_bytes().startswith(b"\x89PNG"))
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                self.assertEqual(cli.main(["card", "--league", L, "--season", "2026", "--week", "1", "--home", "x", "--away", "y"]), 1)
            self.assertIn("no such game", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
