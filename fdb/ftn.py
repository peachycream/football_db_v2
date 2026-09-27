"""FTN Data API client (Phase 5). Every FTN call in this package goes through here.

Facts carried from v1 FTN_API_FINDINGS.md (re-verified live 2026-09-27):
  * https://data.ftndata.com, header `Authorization: <FTN_API_KEY>` - the raw "Legacy"
    key, NO `Bearer`. FTN_USER/FTN_PASS are website credentials, unused.
  * Season endpoints paginate with count/start. Page size is capped PER ENDPOINT
    (/plays: 1000 even when count=2000), so only an EMPTY page ends a season.
  * Post-game product: nothing for a game in progress; charting/participation land
    after the game and are REVISED for months (2025 `updated` stamps in Aug 2026).
  * Feeds advance unevenly (plays runs ahead of participation), so a week is loaded
    only when every scheduled team is present - the framework's team check does that.
"""
import json
import time
import urllib.error

from . import config, http

API = "https://data.ftndata.com"
PAGE = 2000
MIN_INTERVAL = 0.3


class FtnError(RuntimeError):
    pass


_last = [0.0]


def _get(path: str) -> bytes:
    key = config.env("FTN_API_KEY")
    if not key:
        raise FtnError("FTN_API_KEY missing from the environment/.env")
    for attempt in range(4):
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            _, _, body = http.request(f"{API}{path}", headers={"Authorization": key, "Accept": "application/json"},
                                      timeout=180)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise FtnError(f"HTTP {e.code} for {path}: {e.read()[:200].decode('utf-8', 'replace')}") from None
    raise AssertionError("unreachable")


def get(path: str) -> tuple[bytes, dict]:
    """One unpaginated resource (e.g. /games/2026, /all22/game/7019)."""
    body = _get(path)
    json.loads(body)  # must be JSON; an error page is never stored as data
    return body, {"url": f"{API}{path}"}


def get_pages(path: str) -> tuple[bytes, dict]:
    """A paginated season resource. The raw payload is the pages, each exactly as
    received, wrapped in one JSON array: b'[' + page1 + b',' + page2 + ... + b']'."""
    pages, start, cap = [], 0, 0
    while True:
        try:
            body = _get(f"{path}?count={PAGE}&start={start}")
        except FtnError as e:
            # Past the end, /plays answers 404 "Season not found" rather than []. Only
            # accepted as the end after a FULL page (a total that is an exact multiple
            # of the page cap); anywhere else a 404 is an error.
            if start > 0 and "HTTP 404" in str(e) and "Season not found" in str(e):
                break
            raise
        rows = json.loads(body)
        if not isinstance(rows, list):
            raise FtnError(f"{path}: expected a list page, got {type(rows).__name__}: {body[:120]!r}")
        if not rows:
            break
        pages.append(body)
        # NOT `len(rows) < count`: /plays silently caps a page at 1000 whatever `count`
        # says (found 2026-09-27: a whole season came back as 1000 plays). The real cap
        # is the largest page seen; a page shorter than that is the last one.
        cap = max(cap, len(rows))
        start += len(rows)
        if len(rows) < cap:
            break
    return b"[" + b",".join(pages) + b"]", {"url": f"{API}{path}", "pages": str(len(pages)), "count": str(PAGE)}


def flatten(payload: bytes) -> list[dict]:
    """Rows of a get_pages payload."""
    return [r for page in json.loads(payload) for r in page]
