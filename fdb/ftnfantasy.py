"""FTN Fantasy StatsHub client (team DVOA). Every ftnfantasy.com call in this package goes through here.

Not the FTN Data API (fdb/ftn.py, data.ftndata.com): that has no DVOA. ftnfantasy.com/nfl/stats is a
single-page app over two services (read from the site's own bundles, verified live 2026-10-01):
  * login:  POST https://api.ftnfantasy.com/users/login  {"email","password"}
            -> {"status":"success","user_id","access_token","refresh_token"}
  * stats:  POST https://6u5we6fbxi.execute-api.us-east-1.amazonaws.com/Statshub/statshub/dvoa/team
            with `Authorization: Bearer <access_token>` and the page's whole filter object as JSON.
            Answers one row per team that played in the window: offDvoa, defDvoa, totalDvoa, ... .
            `/dvoa/defense` answers byte-identically (checked 2025 wk5), so only `team` is read.
Logged out, the stats call is 401. The filter object is the page's default (`fa` in statshub.js) with
`year`, `weeks` and `seasonType` set; every other filter is left empty. Seasons before 2018 answer [].

Settings (.env, never logged): FTN_USER, FTN_PASS (the website login; FTN_API_KEY is the other service).
"""
import json
import time
import urllib.error

from . import config, http

LOGIN = "https://api.ftnfantasy.com/users/login"
STATS = "https://6u5we6fbxi.execute-api.us-east-1.amazonaws.com/Statshub/statshub"
MIN_GAP_S = 0.4
_state = {"token": None, "last": 0.0}

# The page's default filter object, copied from statshub.js (`fa`). Only year/weeks/seasonType vary.
_FILTERS = dict(
    alignment=[], belowFreezing=None, beyondLine=None, blitz=None, condition=None, coverage=[], coverageType=None,
    defensivePersonnel=[], designedRun=None, distance=[], dome=None, downs=[], favorite=None, firstRead=None,
    insideFive=None, insideTen=None, location=[], motion=[], noHuddle=None, offensivePersonnel=[], opponents=[],
    option=None, outOfPocket=None, playAction=None, ppr=1, precipitation=None, pressure=None, quarters=[],
    quickRelease=None, redZone=None, route=[], runConcept=[], scramble=None, separationType=[], separationYards=[],
    shotgun=None, situation=[], sneak=None, stackedBox=None, teams=[], trickPlay=None, twoMinDrill=None, wind=None,
    yardsToEndzone=None)


class FtnFantasyError(RuntimeError):
    pass


def _setting(name: str) -> str:
    v = config.env(name)
    if not v:
        raise FtnFantasyError(f"{name} missing from the environment/.env")
    return v


def _post(url: str, body: dict, token: str | None = None) -> bytes:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    _, _, raw = http.request(url, data=json.dumps(body).encode(), headers=headers, timeout=120)
    return raw


def login(force: bool = False) -> str:
    """-> access token (kept for the process; a 401 on a call logs in once more)."""
    if _state["token"] and not force:
        return _state["token"]
    try:
        raw = _post(LOGIN, {"email": _setting("FTN_USER"), "password": _setting("FTN_PASS")})
    except urllib.error.HTTPError as e:
        # The body can echo the account; record only the code.
        raise FtnFantasyError(f"FTN Fantasy login refused (HTTP {e.code})") from None
    data = json.loads(raw)
    if data.get("status") != "success" or not data.get("access_token"):
        raise FtnFantasyError("FTN Fantasy login did not succeed")
    _state["token"] = data["access_token"]
    return _state["token"]


def dvoa_team(season: int, week: int, season_type: str = "reg") -> tuple[bytes, dict]:
    """One team-DVOA window = one schedule week. -> (body exactly as received, params safe to record)."""
    filters = {**_FILTERS, "year": season, "weeks": [week], "seasonType": season_type}
    url = f"{STATS}/dvoa/team"
    relogged = False
    for attempt in range(5):
        wait = _state["last"] + MIN_GAP_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _state["last"] = time.time()
        try:
            body = _post(url, filters, login())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and not relogged:   # token rejected: log in once more
                relogged = True
                login(force=True)
                continue
            if e.code in (429, 502, 503, 504) and attempt < 4:
                time.sleep(15 * (attempt + 1))
                continue
            raise FtnFantasyError(f"HTTP {e.code} for dvoa/team {season} wk{week}: {e.read()[:200].decode('utf-8', 'replace')}") from None
        try:
            parsed = json.loads(body)
        except ValueError:
            raise FtnFantasyError(f"dvoa/team {season} wk{week}: not JSON ({body[:80]!r})") from None
        if not isinstance(parsed, list):
            raise FtnFantasyError(f"dvoa/team {season} wk{week}: expected a JSON list, got {type(parsed).__name__}")
        return body, {"url": url, "year": season, "weeks": [week], "seasonType": season_type}
    raise AssertionError("unreachable")
