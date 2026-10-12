"""CollegeFootballData (CFBD) loaders (Phase 14, devy tracker). Live-probed 2026-10-10.

api.collegefootballdata.com, `Authorization: Bearer <CFB_API_KEY>`. The quota is small (1,000 calls a month on
this key), so every loader reads a WHOLE season in one call (stats/player/season ~23 MB, player/usage ~1 MB,
roster ~9 MB) and the weekly job makes three calls a season, not one per team or per player.

A season is final once the NFL season it overlaps has moved on (CFB's bowls end in January, before the NFL
season is current-1 closed); until then the raw file is re-fetched every run and never trusted from cache.
CFBD has NO birthdate: nothing here derives an age.
"""
import json

from .. import config, http, schedule
from ..loader import Loader

API = "https://api.collegefootballdata.com"
KEEP_CATEGORIES = ("passing", "rushing", "receiving", "defensive", "interceptions")
USAGE_KEYS = ("overall", "pass", "rush", "firstDown", "secondDown", "thirdDown", "standardDowns", "passingDowns")


class CfbdSeasonLoader(Loader):
    source = "cfbd"
    ext = "json"
    grain = "season"
    season_range = (2025, 2026)
    path = ""
    min_rows = 1

    def partition(self, scope):
        return str(scope.season)

    def fetch(self, partition):
        key = config.env("CFB_API_KEY")
        if not key:
            raise RuntimeError("CFB_API_KEY missing from the environment/.env")
        url = f"{API}{self.path}?year={int(partition)}"
        body = http.get(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, timeout=300)
        return body, {"url": url}

    def raw_is_final(self, conn, partition):
        cur = schedule.current_season(conn)
        return cur is not None and int(partition) < cur

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def derive(self, row):
        return {"season": self.scope.season}

    def scope_rows(self, rows, scope):
        return rows   # the request named the season

    def _rows(self, payload):
        data = json.loads(payload)
        if not isinstance(data, list):
            raise ValueError(f"{self.id}: expected a JSON list, got {type(data).__name__}: {str(data)[:120]}")
        return data

    def checks(self, conn, scope):
        n = conn.execute(f"SELECT COUNT(*) FROM {self.table} WHERE season = ?", (scope.season,)).fetchone()[0]
        return [] if n >= self.min_rows else [f"{scope.label}: only {n} rows (truncated?)"]


class PlayerSeasonLoader(CfbdSeasonLoader):
    id = "cfbd.player_season"
    endpoint = "stats_player_season"
    table = "core_cfbd_player_season"
    path = "/stats/player/season"
    min_rows = 20000
    warn_new_fields = False

    def parse(self, payload):
        data = self._rows(payload)
        rows = [r for r in data if r.get("category") in KEEP_CATEGORIES]
        return sorted({k for r in data for k in r}), rows

    def scope_rows(self, rows, scope):
        bad = [r for r in rows if r.get("season") != scope.season]
        if bad:
            raise ValueError(f"{scope.label}: payload holds season {bad[0].get('season')}")
        return rows

    def derive(self, row):
        return {}   # `season` is in the source row

    def checks(self, conn, scope):
        fails = super().checks(conn, scope)
        s = scope.season
        over = conn.execute("""SELECT COUNT(*) FROM core_cfbd_player_season c JOIN core_cfbd_player_season a
              ON a.season = c.season AND a.playerId = c.playerId AND a.team = c.team
              AND a.category = 'passing' AND a.statType = 'ATT'
              WHERE c.season = ? AND c.category = 'passing' AND c.statType = 'COMPLETIONS' AND c.stat > a.stat""", (s,)).fetchone()[0]
        if over:
            fails.append(f"{scope.label}: {over} players with more completions than attempts")
        big = conn.execute("SELECT MAX(stat) FROM core_cfbd_player_season WHERE season = ? AND category = 'passing' "
                           "AND statType = 'ATT'", (s,)).fetchone()[0]
        if big is not None and big > 900:
            fails.append(f"{scope.label}: a player with {big} pass attempts")
        neg = conn.execute("SELECT COUNT(*) FROM core_cfbd_player_season WHERE season = ? AND stat < 0 "
                           "AND statType NOT IN ('YDS', 'YPC', 'YPR', 'YPA', 'LONG', 'AVG')", (s,)).fetchone()[0]
        if neg:
            fails.append(f"{scope.label}: {neg} negative counting stats")
        return fails


class PlayerUsageLoader(CfbdSeasonLoader):
    id = "cfbd.player_usage"
    endpoint = "player_usage"
    table = "core_cfbd_player_usage"
    path = "/player/usage"
    min_rows = 2000
    warn_new_fields = False

    def parse(self, payload):
        data = self._rows(payload)
        best = {}
        for r in data:
            u = r.get("usage") or {}
            unknown = set(u) - set(USAGE_KEYS)
            if unknown:
                raise ValueError(f"usage has keys the table lacks: {sorted(unknown)}")
            row = {**{k: v for k, v in r.items() if k != "usage"}, **{f"usage_{k}": u.get(k) for k in USAGE_KEYS}}
            key = (row["season"], row["id"], row["team"])
            old = best.get(key)
            if old is None:
                best[key] = row
                continue
            # CFBD lists some players twice, identical except an empty `conference` (37 of 5,029 in 2026).
            # Collapse only that; a duplicate that differs in any number is a source problem.
            strip = lambda x: {k: v for k, v in x.items() if k != "conference"}
            if strip(old) != strip(row):
                raise ValueError(f"{key}: two usage rows that differ beyond `conference`")
            if not old.get("conference") and row.get("conference"):
                best[key] = row
        return sorted({k for r in data for k in r}), list(best.values())

    def scope_rows(self, rows, scope):
        bad = [r for r in rows if r.get("season") != scope.season]
        if bad:
            raise ValueError(f"{scope.label}: payload holds season {bad[0].get('season')}")
        return rows

    def derive(self, row):
        return {}

    def checks(self, conn, scope):
        fails = super().checks(conn, scope)
        out = conn.execute("SELECT COUNT(*) FROM core_cfbd_player_usage WHERE season = ? AND "
                           "(usage_overall < 0 OR usage_overall > 1)", (scope.season,)).fetchone()[0]
        if out:
            fails.append(f"{scope.label}: {out} usage shares outside 0..1")
        return fails


class RosterLoader(CfbdSeasonLoader):
    id = "cfbd.roster"
    endpoint = "roster"
    table = "core_cfbd_roster"
    path = "/roster"
    min_rows = 15000
    warn_new_fields = False

    def parse(self, payload):
        data = self._rows(payload)
        rows = [{**r, "recruitIds": json.dumps(r.get("recruitIds") or [])} for r in data]
        return sorted({k for r in data for k in r}), rows

    def checks(self, conn, scope):
        fails = super().checks(conn, scope)
        bad = conn.execute("SELECT COUNT(*) FROM core_cfbd_roster WHERE season = ? AND "
                           "((height IS NOT NULL AND height NOT BETWEEN 55 AND 90) OR "
                           "(weight IS NOT NULL AND weight NOT BETWEEN 120 AND 450))", (scope.season,)).fetchone()[0]
        if bad > 25:   # a handful of source typos are normal; a unit change is not
            fails.append(f"{scope.label}: {bad} players with an implausible height or weight")
        return fails


LOADERS = (PlayerSeasonLoader, PlayerUsageLoader, RosterLoader)
