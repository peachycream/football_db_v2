"""DD Fantasy Football Trinity loaders. Client and live-verified source facts: fdb/ddff.py.

Two owners, two tables (a second source never writes the first's table):
  ddff.trinity_aggregates  core_trinity_ftn_aggregates  one raw file per (season, REG week): the weekly
                           FTN counts DD's Trinity Score is computed from, with gsis AND sleeper ids.
  ddff.trinity_scores      core_trinity_scores          DD's own stored season score, closed seasons only.
A week's Trinity Score is NOT served by the site; the page computes it in the browser from the
aggregates. fdb/trinity.py ports that computation into mart_trinity_*; nothing here derives it.

Scope: 2021 onward (the site's own season picker starts there) and REG weeks 1-17 (its week
picker stops there). Weeks come from completed_weeks(); the loader never chooses them.
"""
import json

from .. import ddff as api, schedule
from ..loader import Loader
from .csvbase import WeekCsvLoader

FIRST_SEASON = 2021
POSITIONS = {"WR", "TE", "RB"}

# Weeks DD serves wrongly, found by this loader's own checks on the 2021-2026 backfill (2026-10-01) and kept here so
# the weekly job does not fail on them every Wednesday. Never offered, never fetched; raw already on disk stays.
# Re-test one read at a time if DD says it fixed them (the loader's checks will say whether the week now passes).
SOURCE_DEFECTS = {
    (2021, "REG", 15): "only 25 of 32 teams have rows: ARI-DET, DAL-NYG, ATL-SF and NO-TB (the scheduled games) are absent",
    **{(2024, "REG", w): "games = 2 in a one-week request (Kelce 72 routes in wk14 vs 44 in wk13): the week is double-counted, "
                         "so DD's own 1-17 window for 2024 is inflated too (Kelce 119 rec / 1,034 yds; actual about 97 / 823)"
       for w in (14, 15, 16, 17)},
}


def _rows(payload: bytes) -> list[dict]:
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError(f"expected a JSON list of rows, got {type(rows).__name__}")
    return rows


class TrinityAggregatesLoader(WeekCsvLoader):
    """Team checks come from WeekCsvLoader: every team the schedule had playing must have a row
    (a half-published week is a failure, not a smaller table), and none that wasn't."""
    id = "ddff.trinity_aggregates"
    source = "ddff"
    endpoint = "trinity_ftn_aggregates_week"
    table = "core_trinity_ftn_aggregates"
    ext = "json"
    team_col = "team"
    season_range = (FIRST_SEASON, 9999)
    season_types = ("REG",)
    max_week = 17
    unavailable = SOURCE_DEFECTS
    MIN_ROWS, MAX_ROWS = 150, 600     # week 1 2025 had 316

    def partition(self, scope):
        return f"{scope.season}/REG{scope.week:02d}"

    @staticmethod
    def _split(partition):
        season, rest = partition.split("/")
        return int(season), int(rest[3:])

    def fetch(self, partition):
        season, week = self._split(partition)
        body, params = api.rpc("trinity_ftn_aggregates_weeks", {"p_season": season, "p_weeks": [week]})
        return body, params

    def parse(self, payload):
        rows = _rows(payload)
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        return rows   # the request named the week; the file IS the scope

    def derive(self, row):
        s = self.scope
        return {"season": s.season, "season_type": "REG", "week": s.week}

    def raw_is_final(self, conn, partition):
        # DD re-derives from FTN charting, which lags and revises; only a CLOSED season is final.
        # In-season weeks are re-fetched each run (<= 17 reads against the account's quota).
        return schedule.season_is_closed(conn, self._split(partition)[0])

    def extra_checks(self, conn, scope):
        where, params = self.scope_where(scope)
        n, games, odd_pos = conn.execute(
            f"SELECT COUNT(*), MAX(games), SUM(pos NOT IN ('WR','TE','RB')) FROM {self.table} WHERE {where}", params).fetchone()
        fails = []
        if not self.MIN_ROWS <= n <= self.MAX_ROWS:
            fails.append(f"{scope.label}: {n} player rows (expected {self.MIN_ROWS}-{self.MAX_ROWS}; truncated or duplicated?)")
        if games and games > 1:
            fails.append(f"{scope.label}: games = {games} in a one-week request")
        if odd_pos:
            fails.append(f"{scope.label}: {odd_pos} rows outside WR/TE/RB")
        # Counts cannot be negative. Air yards, receiving yards and YAC legitimately can (behind-the-line targets):
        # 2,933 / 266 / 128 such rows in 2021-2026, so they are NOT checked.
        neg = conn.execute(f"""SELECT COUNT(*) FROM {self.table} WHERE {where} AND
                               (routes < 0 OR targets < 0 OR rec < 0 OR rec_td < 0 OR first_downs < 0 OR games < 0)""", params).fetchone()[0]
        if neg:
            fails.append(f"{scope.label}: {neg} rows with a negative count")
        return fails


class TrinityScoresLoader(Loader):
    """DD's stored season score (sleeper_id on every row). One raw file per season, pages of 250
    joined into one JSON list. Closed seasons only: an in-progress season's number is computed by
    the mart from the weekly aggregates instead."""
    id = "ddff.trinity_scores"
    source = "ddff"
    endpoint = "trinity_scores_season"
    table = "core_trinity_scores"
    ext = "json"
    grain = "season"
    season_range = (FIRST_SEASON, 9999)
    closed_seasons_only = True
    MIN_ROWS = 200

    def partition(self, scope):
        return str(scope.season)

    def fetch(self, partition):
        rows, params = api.paged("gated_trinity_scores", {"_season": int(partition), "_positions": None, "_teams": None})
        return json.dumps(rows, separators=(",", ":")).encode(), params

    def parse(self, payload):
        rows = _rows(payload)
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        other = {r.get("season") for r in rows} - {scope.season}
        if other:
            raise ValueError(f"{scope.label}: payload holds season(s) {sorted(map(str, other))}")
        return rows

    def derive(self, row):
        return {"season_type": "REG"}

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def raw_is_final(self, conn, partition):
        return schedule.season_is_closed(conn, int(partition))

    def checks(self, conn, scope):
        n, lo, hi, odd_pos = conn.execute("""SELECT COUNT(*), MIN(trinity_score), MAX(trinity_score),
                                  SUM(position NOT IN ('WR','TE','RB')) FROM core_trinity_scores WHERE season = ?""",
                                          (scope.season,)).fetchone()
        fails = []
        if n < self.MIN_ROWS:
            fails.append(f"{scope.label}: only {n} players (truncated?)")
        if lo is not None and not (0 <= lo and hi <= 10):
            fails.append(f"{scope.label}: trinity_score outside 0-10 ({lo}..{hi})")
        if odd_pos:
            fails.append(f"{scope.label}: {odd_pos} rows outside WR/TE/RB")
        return fails


LOADERS = (TrinityAggregatesLoader, TrinityScoresLoader)
