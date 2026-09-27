"""PFF Developer API client (Phase 4). Every PFF call in this package goes through here.

Facts carried from v1 PFF_API_FINDINGS.md (re-verified live in Phase 4):
  * https://api.pff.com, `Authorization: Bearer <PFF_API_KEY>` (PFF_USER/PFF_PASS are
    website credentials and do NOT work on the API). Accept application/json only.
  * 100 reads/min, shared across the account. Every counted response carries
    x-ratelimit-remaining/-reset: throttle BEFORE being told to. 429 -> Retry-After.
  * It fails quietly three ways, none a non-200:
      - `restricted_columns` in the body = columns silently withheld (entitlement)
      - 200 with 0 rows is the normal empty answer
      - seasons listed by ref-leagues may hold 2 placeholder rows
    So: restricted_columns raises; emptiness is judged by the framework, never cached.
  * Errors: {"error": {"code", "message", "request_id"}}. Branch on code.
"""
import json
import time
import urllib.error
import urllib.parse

from . import config, http

API = "https://api.pff.com"
LOW_WATER = 5            # remaining reads at which we wait for the window to reset
_state = {"remaining": None, "reset": None}


class PffError(RuntimeError):
    pass


def _key() -> str:
    k = config.env("PFF_API_KEY")
    if not k:
        raise PffError("PFF_API_KEY missing from the environment/.env")
    return k


def _throttle():
    rem, reset = _state["remaining"], _state["reset"]
    if rem is not None and rem <= LOW_WATER:
        wait = max(2.0, (reset or time.time() + 60) - time.time() + 1)
        print(f"[pff] {rem} reads left in the window; waiting {wait:.0f}s")
        time.sleep(wait)
        _state["remaining"] = None


def get(path: str, **params) -> tuple[bytes, dict]:
    """-> (body exactly as received, params safe to record). Raises PffError on an
    error payload, a non-JSON body, or restricted_columns."""
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, safe=",")
    url = f"{API}{path}?{q}"
    headers = {"Authorization": f"Bearer {_key()}", "Accept": "application/json"}
    for attempt in range(6):
        _throttle()
        try:
            _, hdrs, body = http.request(url, headers=headers, timeout=120)
        except urllib.error.HTTPError as e:
            # 429/503 carry Retry-After; 502/504 are upstream_timeout on heavy
            # server-aggregated calls (season grades), transient in practice.
            if e.code in (429, 502, 503, 504) and attempt < 5:
                wait = float(e.headers.get("Retry-After") or 20 * (attempt + 1))
                print(f"[pff] HTTP {e.code}; retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            detail = e.read()[:300].decode("utf-8", "replace")
            raise PffError(f"HTTP {e.code} for {path} {params}: {detail}") from None
        rem = hdrs.get("x-ratelimit-remaining")
        reset = hdrs.get("x-ratelimit-reset")
        _state["remaining"] = int(rem) if rem is not None else None
        _state["reset"] = float(reset) if reset is not None else None
        try:
            data = json.loads(body)
        except ValueError:
            raise PffError(f"{path} {params}: not JSON ({body[:80]!r})") from None
        if isinstance(data, dict) and "error" in data:
            raise PffError(f"{path} {params}: {data['error'].get('code')}: {data['error'].get('message')}")
        if isinstance(data, dict) and data.get("restricted_columns"):
            # Absence of this key is the only proof nothing was withheld.
            raise PffError(f"{path} {params}: restricted_columns {data['restricted_columns']} - "
                           "entitlement is partial; the load would silently lose columns")
        return body, {"url": f"{API}{path}", **{k: str(v) for k, v in params.items() if v is not None}}
    raise AssertionError("unreachable")


def rows_of(data: dict) -> tuple[str, list]:
    """The report's row list: the one top-level key holding a list of dicts
    (e.g. 'defense_summary'). Anything else is refused - a probe that reads the
    wrong key reports 0 rows and would look like an empty week."""
    lists = {k: v for k, v in data.items() if isinstance(v, list)}
    if len(lists) != 1:
        raise ValueError(f"expected one row list in the PFF payload, found keys {sorted(data)}")
    return next(iter(lists.items()))
