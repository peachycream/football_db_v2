"""DD Fantasy Football client (Trinity). Every ddfantasyfootball.com call in this package goes through here.

The site is a Supabase app. Its Trinity pages read two things with a logged-in
member session (verified live 2026-10-01 by driving the page, nothing else):
  * `trinity_ftn_aggregates_weeks(p_season, p_weeks)`: per-player FTN counts for the
    weeks asked, with the player's gsis id AND sleeper id on every row. The page
    turns these into a Trinity Score in the browser (fdb/trinity.py ports that).
  * `gated_trinity_scores(_season, _positions, _teams, _limit, _offset)`: DD's stored
    season-long score per player (sleeper_id on every row), 250 rows a page.
Both are member-gated and read-quota'd per account ("read_quota_exceeded"); the site's
own pages stop at 2021 and at week 17.

Auth is Supabase password login: POST /auth/v1/token?grant_type=password with the public
`apikey`. Settings (all in .env, never logged): DDFF_SUPABASE_URL, DDFF_SUPABASE_KEY,
DDFF_EMAIL, DDFF_PASSWORD.
"""
import json
import time
import urllib.error

from . import config, http

MIN_GAP_S = 0.4          # courtesy gap between calls; the account has a read quota
PAGE = 250               # the site's own page size for gated reads
_state = {"token": None, "exp": 0.0, "last": 0.0}


class DdffError(RuntimeError):
    pass


def _setting(name: str) -> str:
    v = config.env(name)
    if not v:
        raise DdffError(f"{name} missing from the environment/.env")
    return v


def _base() -> str:
    return _setting("DDFF_SUPABASE_URL").rstrip("/")


def _headers(token: str | None = None) -> dict:
    h = {"apikey": _setting("DDFF_SUPABASE_KEY"), "Content-Type": "application/json", "Accept": "application/json"}
    h["Authorization"] = f"Bearer {token or _setting('DDFF_SUPABASE_KEY')}"
    return h


def login(force: bool = False) -> str:
    """-> access token (cached until shortly before it expires)."""
    if not force and _state["token"] and time.time() < _state["exp"] - 120:
        return _state["token"]
    body = json.dumps({"email": _setting("DDFF_EMAIL"), "password": _setting("DDFF_PASSWORD")}).encode()
    try:
        _, _, raw = http.request(f"{_base()}/auth/v1/token?grant_type=password", data=body, headers=_headers(), timeout=60)
    except urllib.error.HTTPError as e:
        # The response can echo the account name; record only the code and the source's own message.
        try:
            err = json.loads(e.read())
            msg = err.get("msg") or err.get("error_description")
        except Exception:
            msg = None
        raise DdffError(f"DD login refused (HTTP {e.code}{': ' + str(msg) if msg else ''})") from None
    data = json.loads(raw)
    if not data.get("access_token"):
        raise DdffError("DD login returned no access_token")
    _state["token"] = data["access_token"]
    _state["exp"] = time.time() + float(data.get("expires_in") or 3600)
    return _state["token"]


def _gap():
    wait = _state["last"] + MIN_GAP_S - time.time()
    if wait > 0:
        time.sleep(wait)
    _state["last"] = time.time()


def rpc(fn: str, args: dict) -> tuple[bytes, dict]:
    """-> (body exactly as received, params safe to record). Raises DdffError on an
    error payload (quota, auth, permission), a non-JSON body or a non-list answer."""
    url = f"{_base()}/rest/v1/rpc/{fn}"
    data = json.dumps(args).encode()
    relogged = False
    for attempt in range(5):
        _gap()
        try:
            _, _, body = http.request(url, data=data, headers=_headers(login()), timeout=120)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if e.code == 401 and not relogged:      # token rejected: log in once more
                relogged = True
                login(force=True)
                continue
            if e.code in (429, 502, 503, 504) and attempt < 4:
                wait = float(e.headers.get("Retry-After") or 15 * (attempt + 1))
                print(f"[ddff] HTTP {e.code}; retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            raise DdffError(f"HTTP {e.code} for {fn}: {_explain(detail)}") from None
        try:
            parsed = json.loads(body)
        except ValueError:
            raise DdffError(f"{fn}: not JSON ({body[:80]!r})") from None
        if isinstance(parsed, dict):   # PostgREST error shape: {"code","message","details","hint"}
            raise DdffError(f"{fn}: {_explain(json.dumps(parsed)[:300])}")
        if not isinstance(parsed, list):
            raise DdffError(f"{fn}: expected a JSON list, got {type(parsed).__name__}")
        return body, {"url": url, "fn": fn, "args": json.dumps(args, sort_keys=True)}
    raise AssertionError("unreachable")


def _explain(text: str) -> str:
    low = text.lower()
    for key, meaning in (("read_quota_exceeded", "the account's read quota is used up"),
                         ("membership_required", "this account lacks the membership the read needs"),
                         ("email_unverified", "the account's email is not verified"),
                         ("unauthenticated", "not authenticated"),
                         ("offset_too_deep", "paged too deep"),
                         ("permission denied", "permission denied")):
        if key in low:
            return f"{key} ({meaning})"
    return text


def paged(fn: str, args: dict, max_rows: int = 20000) -> tuple[list[dict], dict]:
    """Gated reads page with `_limit`/`_offset`. -> (all rows, params of the first call)."""
    rows, params, off = [], None, 0
    while off < max_rows:
        body, p = rpc(fn, {**args, "_limit": PAGE, "_offset": off})
        params = params or {k: v for k, v in p.items() if k != "args"} | {"args": json.dumps(args, sort_keys=True)}
        page = json.loads(body)
        if not page:
            break
        rows += page
        off += len(page)
    return rows, params or {}
