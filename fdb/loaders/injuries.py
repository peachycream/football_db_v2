"""Injury-status loaders (Phase 12): the NFL's weekly report (nflverse) and MFL's current list.

Both are current-state feeds, never final until the season closes, re-fetched on every run. Source facts,
probed live 2026-10-04 (schema/030_core_injuries.sql has the field-level detail):
  * nflverse injuries_<season>.csv: 2016-2024 and 2025+ have different headers, so only 2025+ is read. The 2026
    file held weeks 1-4 on the 4th (week 5's report is published Wednesday), so a week with no rows means
    "not published yet", never "everyone is healthy" (fdb/alerts.py relies on this).
  * MFL TYPE=injuries answers {"injuries": {"timestamp", "week", "injury": [{id, status, details, exp_return}]}}
    with no login; the list is league-independent.
"""
import gzip
import json
import re

from .. import http, mfl, schedule
from ..loader import Loader, Scope
from .csvbase import CsvLoader

NFL_GAME_STATUS = {None, "", "Out", "Doubtful", "Questionable"}
NFL_PRACTICE_STATUS = {None, "", "Full Participation in Practice", "Limited Participation in Practice",
                       "Did Not Participate In Practice"}


class NflInjuriesLoader(CsvLoader):
    id = "nflverse.injuries"
    source = "nflverse"
    endpoint = "injuries"
    table = "core_nflverse_injuries"
    grain = "season"
    season_range = (2025, 2099)   # earlier files have another header; see the module docstring
    url_template = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
    ROWS_PER_WEEK = (50, 700)     # observed 2025: ~275 per REG week; bounds catch a truncated or duplicated file
    # Playoff weeks have fewer teams (2025 POST: 44 and 20 rows), so only the ceiling applies to them.

    def partition(self, scope: Scope) -> str:
        return str(scope.season)

    def scope_rows(self, rows, scope):
        return [r for r in rows if r["season"] and int(r["season"]) == scope.season]

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def raw_is_final(self, conn, partition):
        return schedule.season_is_closed(conn, int(partition))

    def checks(self, conn, scope):
        s, fails = scope.season, []
        lo, hi = self.ROWS_PER_WEEK
        odd = conn.execute("""SELECT season_type, week, COUNT(*) FROM core_nflverse_injuries WHERE season = ?
                              GROUP BY season_type, week
                              HAVING COUNT(*) > ? OR (season_type = 'REG' AND COUNT(*) < ?)""", (s, hi, lo)).fetchall()
        if odd:
            fails.append(f"{s}: weeks with implausible row counts (REG {lo}-{hi}, POST up to {hi}): {[tuple(o) for o in odd][:5]}")
        # A status the alert engine has no wording for must stop the load, not pass as 'no designation'.
        for col, known in (("report_status", NFL_GAME_STATUS), ("practice_status", NFL_PRACTICE_STATUS)):
            got = {r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM core_nflverse_injuries WHERE season = ?", (s,))}
            if got - known:
                fails.append(f"{s}: unknown {col} values {sorted(got - known)}")
        unmapped = conn.execute("""SELECT DISTINCT team FROM core_nflverse_injuries r WHERE season = ? AND NOT EXISTS
                (SELECT 1 FROM team_aliases a WHERE a.abbr = r.team AND ? BETWEEN a.season_from AND a.season_to)""",
                                (s, s)).fetchall()
        if unmapped:
            fails.append(f"{s}: team values with no team_aliases row: {[r[0] for r in unmapped]}")
        bad = conn.execute("SELECT COUNT(*) FROM core_nflverse_injuries WHERE season = ? AND week NOT BETWEEN 1 AND 22",
                           (s,)).fetchone()[0]
        if bad:
            fails.append(f"{s}: {bad} rows with a week outside 1-22")
        return fails


class MflInjuriesLoader(Loader):
    id = "mfl.injuries"
    source = "mfl"
    endpoint = "injuries"
    table = "core_mfl_injuries"
    grain = "snapshot"
    ext = "json"
    ROWS = (50, 3000)             # observed 447; MFL lists every injured/retired player

    def partition(self, scope: Scope) -> str:
        return "all"

    def prepare(self, conn):
        self._season = schedule.current_season(conn)

    def fetch(self, partition):
        if not self._season:
            raise RuntimeError("no current season in the schedule; cannot name the MFL year")
        url = f"{mfl.API}/{self._season}/export?TYPE=injuries&JSON=1"
        # The year goes in the sidecar so load() reads the same season on a rebuild (the clock must not decide it).
        return http.get(url), {"url": url, "season": self._season}

    def parse(self, payload):
        d = json.loads(payload)
        if not isinstance(d, dict) or "error" in d:
            raise ValueError(f"MFL injuries answered an error payload: {str(d)[:120]}")
        inj = d.get("injuries") or {}
        rows = [{**r, "week": inj.get("week"), "timestamp": inj.get("timestamp") or None}
                for r in mfl.as_list(inj.get("injury"))]
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        return rows

    def scope_where(self, scope):
        return "1 = 1", ()

    def derive(self, row):
        return {"season": int(self.raw_rec.params["season"])}

    def raw_is_final(self, conn, partition):
        return False

    def checks(self, conn, scope):
        n, weeks = conn.execute("SELECT COUNT(*), COUNT(DISTINCT week) FROM core_mfl_injuries").fetchone()
        lo, hi = self.ROWS
        fails = [] if lo <= n <= hi else [f"{n} injury rows; expected {lo}-{hi} (truncated?)"]
        if weeks != 1:
            fails.append(f"{weeks} distinct weeks in one response")
        if conn.execute("SELECT COUNT(*) FROM core_mfl_injuries WHERE week NOT BETWEEN 1 AND 22").fetchone()[0]:
            fails.append("a week outside 1-22")
        return fails


ESPN_SEASON_TYPES = {2: "REG", 3: "POST"}   # ESPN's own codes; 1 = preseason is never loaded (rule 5)
ESPN_CARD_ID = re.compile(r"/nfl/player/(?:stats/)?_/id/(\d+)/")


class EspnInjuriesLoader(Loader):
    """ESPN's league-wide injuries feed: the only free source with a time per entry and the game-day active/inactive
    word. Facts, each measured 2026-10-04 (schema/031_core_espn_injuries.sql has the long version): one call returns
    all 32 teams; gzip makes it 348 KB; the player id is ONLY in the player-card link; the per-game summary endpoint
    is capped at 5 entries a team and is not used."""
    id = "espn.injuries"
    source = "espn"
    endpoint = "injuries"
    table = "core_espn_injuries"
    grain = "snapshot"
    ext = "json"
    warn_new_fields = False   # the athlete block carries headshots, logos and links that are deliberately not stored
    URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
    ROWS = (200, 3000)        # observed 800

    def partition(self, scope: Scope) -> str:
        return "all"

    def fetch(self, partition):
        body = http.get(self.URL, headers={"Accept-Encoding": "gzip"})
        if body[:2] == b"\x1f\x8b":   # stored decompressed: the raw file is the response as the framework parses it
            body = gzip.decompress(body)
        return body, {"url": self.URL}

    def parse(self, payload):
        d = json.loads(payload)
        season = (d or {}).get("season") or {}
        stype = ESPN_SEASON_TYPES.get(season.get("type"))
        if stype is None:
            raise ValueError(f"ESPN injuries feed is for season type {season.get('type')!r} ({season.get('displayName')}); "
                             "only regular season and postseason are loaded")
        rows = []
        for group in d.get("injuries") or []:
            for i in group.get("injuries") or []:
                a = i.get("athlete") or {}
                ids = {m for link in a.get("links") or [] for m in ESPN_CARD_ID.findall(link.get("href", ""))}
                if len(ids) != 1:   # exact key or nothing: never a name
                    raise ValueError(f"ESPN entry for {a.get('displayName')!r} yields {len(ids)} player ids in its card links: {sorted(ids)}")
                det = i.get("details") or {}
                rows.append({
                    "season": season.get("year"), "season_type": stype, "timestamp": d.get("timestamp"),
                    "espn_player_id": ids.pop(), "team": (a.get("team") or {}).get("abbreviation"),
                    "position": (a.get("position") or {}).get("abbreviation"),
                    "status": i.get("status"), "date": i.get("date"),
                    "shortComment": i.get("shortComment"), "longComment": i.get("longComment"),
                    "details_fantasyStatus": (det.get("fantasyStatus") or {}).get("description"),
                    "details_type": det.get("type"), "details_location": det.get("location"),
                    "details_detail": det.get("detail"), "details_side": det.get("side"),
                    "details_returnDate": det.get("returnDate")})
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        return rows

    def scope_where(self, scope):
        return "1 = 1", ()

    def raw_is_final(self, conn, partition):
        return False

    def checks(self, conn, scope):
        n = conn.execute("SELECT COUNT(*) FROM core_espn_injuries").fetchone()[0]
        lo, hi = self.ROWS
        fails = [] if lo <= n <= hi else [f"{n} injury rows; expected {lo}-{hi} (truncated?)"]
        # A team name the schedule cannot be joined through would silently drop a game's players from the final check.
        unmapped = conn.execute("""SELECT DISTINCT team FROM core_espn_injuries e WHERE NOT EXISTS
                (SELECT 1 FROM team_aliases a WHERE a.abbr = e.team AND e.season BETWEEN a.season_from AND a.season_to)""").fetchall()
        if unmapped:
            fails.append(f"team values with no team_aliases row: {[r[0] for r in unmapped]}")
        bad = conn.execute("SELECT COUNT(*) FROM core_espn_injuries WHERE status IS NULL OR date IS NULL OR team IS NULL").fetchone()[0]
        if bad:
            fails.append(f"{bad} entries with no status, date or team")
        return fails


LOADERS = (NflInjuriesLoader, MflInjuriesLoader, EspnInjuriesLoader)
