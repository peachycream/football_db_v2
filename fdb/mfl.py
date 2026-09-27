"""MyFantasyLeague API client. Every MFL call in this package goes through here.

Facts carried from v1 and re-verified live on 2026-09-26 (REBUILD_LOG Phase 3):
  * Auth: /<year>/login -> cookie MFL_USER_ID. It is sent as a cookie AND as
    APIKEY on export calls. Neither ever reaches a raw sidecar or a log line.
  * Each league lives on its own host (www46..., www49...) per YEAR; the
    league export's `baseURL` names it. Discovered per (league, year).
  * MFL answers bursts with 429, and sometimes with HTTP 200 + {"error": ...}.
    Requests are spaced MIN_INTERVAL apart and 429s back off exponentially.
  * JSON quirk: a list with one member arrives as a bare object. `as_list`
    normalises it; every parser uses it.
"""
import json
import time
import urllib.error
import urllib.parse

from . import config, http

API = "https://api.myfantasyleague.com"
MIN_INTERVAL = 1.1          # seconds between calls; v1 measured 3/s as too fast
BACKOFF = (5, 15, 45, 135)  # seconds, on 429

COOLDOWN = 300              # seconds: after retries are exhausted, fail fast instead of hammering
_token: dict = {}           # year -> token
_hosts: dict = {}           # (league, year) -> https://wwwNN.myfantasyleague.com
_last = [0.0]
_cooldown_until = [0.0]
interval = [MIN_INTERVAL]   # a loader may widen the spacing (playerScores: see loaders/mfl.py)


class MflError(RuntimeError):
    """MFL refused the request (auth, bad league, error payload)."""


def as_list(x) -> list:
    """MFL's one-element-list quirk: None -> [], dict -> [dict], list -> list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _throttle():
    wait = interval[0] - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def login(year: int) -> str:
    if year in _token:
        return _token[year]
    user, pw = config.env("MFL_USERNAME"), config.env("MFL_PASSWORD")
    if not user or not pw:
        raise MflError("MFL_USERNAME / MFL_PASSWORD missing from the environment/.env")
    body = urllib.parse.urlencode({"USERNAME": user, "PASSWORD": pw, "XML": 1}).encode()
    _throttle()
    # POST keeps the password out of any URL that could be logged.
    _, headers, payload = http.request(f"{API}/{year}/login", data=body,
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    token = None
    for cookie in headers.get_all("Set-Cookie") or []:
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("MFL_USER_ID="):
                token = urllib.parse.unquote(part.split("=", 1)[1])
    if not token:
        text = payload.decode("utf-8", "replace")
        raise MflError(f"MFL login returned no MFL_USER_ID cookie ({text[:120]!r})".replace(pw, "***"))
    _token[year] = token
    return token


def _get(url: str, token: str | None) -> bytes:
    headers = {"Cookie": f"MFL_USER_ID={urllib.parse.quote(token, safe='')}"} if token else {}
    if time.time() < _cooldown_until[0]:
        raise MflError(f"MFL rate limit cooldown until {time.strftime('%H:%M:%S', time.localtime(_cooldown_until[0]))}; "
                       f"not calling {_redact(url)}")
    for attempt in range(len(BACKOFF) + 1):
        _throttle()
        try:
            _, _, body = http.request(url, headers=headers)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < len(BACKOFF):
                print(f"[mfl] 429; backing off {BACKOFF[attempt]}s")
                time.sleep(BACKOFF[attempt])
                continue
            if e.code == 429:
                _cooldown_until[0] = time.time() + COOLDOWN
            raise MflError(f"HTTP {e.code} from MFL for {_redact(url)}") from None
    raise AssertionError("unreachable")


def _redact(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    q = [(k, "***" if k.upper() == "APIKEY" else v) for k, v in urllib.parse.parse_qsl(parts.query)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def _check(body: bytes, what: str) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        raise MflError(f"{what}: not JSON ({body[:80]!r})") from None
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        msg = err.get("$t", err) if isinstance(err, dict) else err
        raise MflError(f"{what}: MFL error payload: {msg}")
    return data


def host(league: str, year: int) -> str:
    key = (league, year)
    if key not in _hosts:
        body = _get(f"{API}/{year}/export?" + urllib.parse.urlencode({"TYPE": "league", "L": league, "JSON": 1}),
                    login(year))
        base = (_check(body, f"league {league}/{year}").get("league") or {}).get("baseURL", "").rstrip("/")
        if not base.startswith("https://"):
            raise MflError(f"no baseURL for league {league}/{year}")
        _hosts[key] = base
    return _hosts[key]


def export(year: int, league: str | None, type_: str, **params) -> tuple[bytes, dict]:
    """-> (raw body exactly as received, params safe to record). Raises MflError
    on an error payload, so an error is never written to the raw store as data."""
    token = login(year)
    q = {"TYPE": type_, "JSON": 1, **{k: v for k, v in params.items() if v is not None}}
    if league:
        q["L"] = league
    base = host(league, year) if league else API
    url = f"{base}/{year}/export?" + urllib.parse.urlencode(q)
    body = _get(url, token)
    _check(body, f"{type_} {league}/{year}")
    return body, {"url": f"{base}/{year}/export", **{k: str(v) for k, v in q.items()}}
