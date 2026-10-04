"""PNG renderer for the Matchup of the Week card: the HTML of fdb/matchup_card.py, screenshot by headless Chromium
(Playwright, as v1 did) at 2x. It is the image a Discord job would post and the image `/matchup/card.png` shows, so
reviewing the page shows exactly what would go out. This module NEVER posts anything.

Franchise logos are MFL-hosted images. They are downloaded ONCE (through fdb/http.py, the only network path), cached
under data/cache/logos, sniffed by their magic bytes (the server's content type is not trusted), size-capped, and
embedded as data URIs, so a render never depends on a live fetch and Discord never has to fetch anything. A logo that
cannot be had is simply absent: the card falls back to its abbreviation ring. A render that cannot run raises
RenderError with the reason; it never returns a blank image."""
import base64
import hashlib
import re
import time
from pathlib import Path

from . import config, http, matchup_card as mc, matchup_weeks

CARDS_DIR = config.ROOT / "data" / "cards"
LOGO_DIR = config.ROOT / "data" / "cache" / "logos"
MAX_LOGO_BYTES = 1_500_000
MISS_RETRY_SECONDS = 24 * 3600      # a logo that failed is not retried for a day
SCALE = 2
VIEWPORT_WIDTH = 720                # the card is 680 wide; the page around it is just a dark ground
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"))


class RenderError(RuntimeError):
    pass


def sniff(data: bytes):
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def fetch_logo(url):
    """-> a data URI for the logo, or None. Cached on disk; never raises."""
    if not url or not re.match(r"^https?://", url):
        return None
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    hit = next(iter(sorted(LOGO_DIR.glob(key + ".*"))), None)
    if hit is not None and hit.suffix != ".miss":
        data = hit.read_bytes()
        mime = sniff(data)
        if mime:
            return f"data:{mime};base64," + base64.b64encode(data).decode()
    miss = LOGO_DIR / (key + ".miss")
    if miss.exists() and time.time() - miss.stat().st_mtime < MISS_RETRY_SECONDS:
        return None
    try:
        data = http.get(url, timeout=30)
        mime = sniff(data)
        if not mime or len(data) > MAX_LOGO_BYTES:
            raise ValueError("not a small PNG/JPEG/GIF/WEBP")
    except Exception:   # a logo is decoration: any failure means "no logo", recorded so the next render does not wait on it
        miss.write_bytes(b"")
        return None
    miss.unlink(missing_ok=True)
    (LOGO_DIR / (key + "." + mime.split("/")[1])).write_bytes(data)
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def embed_logos(card: dict) -> dict:
    out = {**card, "home": {**card["home"]}, "away": {**card["away"]}}
    for who in ("home", "away"):
        out[who]["logo"] = fetch_logo(out[who].get("logo"))
    return out


def standalone_html(card: dict) -> str:
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Matchup card</title></head>'
            f'<body style="margin:0;padding:0;background:#0d1220">{mc.card_html(card)}</body></html>')


def render_png(card: dict, scale: int = SCALE, embed: bool = True) -> bytes:
    """The card as PNG bytes. embed=False renders the logos by URL (tests and offline checks)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RenderError("playwright is not installed (pip install playwright && playwright install chromium)") from None
    html = standalone_html(embed_logos(card) if embed else card)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": VIEWPORT_WIDTH, "height": 1000}, device_scale_factor=scale)
                page.set_default_timeout(30000)
                page.set_content(html, wait_until="load")
                page.wait_for_function("Array.from(document.images).every(i => i.complete)")
                el = page.query_selector(".mc")
                if el is None:
                    raise RenderError("the card element was not in the rendered page")
                png = el.screenshot(type="png")
            finally:
                browser.close()
    except RenderError:
        raise
    except Exception as e:
        raise RenderError(f"headless Chromium failed: {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}") from e
    if not png.startswith(b"\x89PNG"):
        raise RenderError("the screenshot is not a PNG")
    return png


def filename(card: dict) -> str:
    h, a = card["home"]["id"], card["away"]["id"]
    return f"{card['league_id']}_{card['season']}_wk{card['week']:02d}_{card['state'].lower()}_{a}_at_{h}.png"


def render_to_file(conn, league=None, season=None, week=None, home=None, away=None, out=None, mode=None):
    """-> (path, card dict). Defaults to the newest week of the league and its FEATURED game (the picker's top game).
    mode='recap' or 'preview' is what a job asks for: the week comes from fdb/matchup_weeks.py (the latest week with results
    loaded, or the next week that has not kicked off) and its featured game; if that target is not ready this raises
    RenderError with the reason instead of rendering the wrong week."""
    if mode:
        if week or home or away:
            raise RenderError("--mode picks the week and the game itself; do not combine it with --week/--home/--away")
        target = (matchup_weeks.recap_target if mode == "recap" else matchup_weeks.preview_target)(conn, league, season)
        if not target["ready"]:
            raise RenderError(f"{mode}: {target['reason']}")
        league, season, week = target["league"], target["season"], target["week"]
        home, away = target["featured"]["home_id"], target["featured"]["away_id"]
    league, season, week = mc.resolve(conn, league, season, week)
    if league is None:
        raise RenderError("no matchup data yet (run fdb weekly)")
    if not (home and away):
        gs = mc.games(conn, league, season, week)
        if not gs:
            raise RenderError(f"no games for {league} {season} week {week}")
        home, away = gs[0]["home_id"], gs[0]["away_id"]
    card = mc.card(conn, league, season, week, home, away)
    if card is None:
        raise RenderError(f"no such game: {league} {season} week {week} {away} at {home}")
    png = render_png(card)
    path = Path(out) if out else CARDS_DIR / filename(card)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path, card
