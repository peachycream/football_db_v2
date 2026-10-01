"""FTN Fantasy team DVOA loader. Client and live-verified source facts: fdb/ftnfantasy.py.

  ftnfantasy.dvoa_team  core_ftn_dvoa_team_week  one raw file per (season, REG week): offense, defense and
                        total DVOA for each team that played that week.
The weekly request names exactly one week, so each row is that week's single-game DVOA. Season-to-date DVOA is
a different (opponent-adjusted) number the site computes for a multi-week window; it is not summed from these.
Scope: 2018 onward (the site answers [] before) and REG weeks. Weeks come from completed_weeks().
"""
import json

from .. import ftnfantasy as api, schedule
from .csvbase import WeekCsvLoader

FIRST_SEASON = 2018

# Weeks the site does not serve, found by the 2018-2026 backfill (2026-10-01) and kept here so the weekly job does not
# fail on them. Never offered, never fetched. Re-test with one read if FTN says it filled the gap.
SOURCE_DEFECTS = {
    (2022, "REG", 5): "answers [] for a one-week request, and a weeks 1-5 window counts 4 games: the week is missing at the source",
}


class DvoaTeamLoader(WeekCsvLoader):
    """Team checks come from WeekCsvLoader: every team the schedule had playing has a row and none that
    wasn't (a bye team correctly has none)."""
    id = "ftnfantasy.dvoa_team"
    source = "ftnfantasy"
    endpoint = "statshub_dvoa_team"
    table = "core_ftn_dvoa_team_week"
    ext = "json"
    team_col = "team"
    season_range = (FIRST_SEASON, 9999)
    season_types = ("REG",)
    unavailable = SOURCE_DEFECTS
    BOUND = 3.0      # single-game DVOA seen so far is within +-1.5; beyond 3 is a unit or scale error

    def partition(self, scope):
        return f"{scope.season}/REG{scope.week:02d}"

    @staticmethod
    def _split(partition):
        season, rest = partition.split("/")
        return int(season), int(rest[3:])

    def fetch(self, partition):
        season, week = self._split(partition)
        return api.dvoa_team(season, week)

    def parse(self, payload):
        rows = json.loads(payload)
        if not isinstance(rows, list):
            raise ValueError(f"expected a JSON list of rows, got {type(rows).__name__}")
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        return rows   # the request named the week; the file IS the scope

    def derive(self, row):
        s = self.scope
        return {"season": s.season, "season_type": "REG", "week": s.week}

    def raw_is_final(self, conn, partition):
        # DVOA is opponent-adjusted and the site re-derives it as the season goes on; only a CLOSED season is final.
        # In-season weeks are re-fetched each run (<= 18 small reads).
        return schedule.season_is_closed(conn, self._split(partition)[0])

    def extra_checks(self, conn, scope):
        where, params = self.scope_where(scope)
        t = self.table
        n, bad_games, nulls, out_of_range = conn.execute(f"""
            SELECT COUNT(*), SUM(games IS NOT 1), SUM(offDvoa IS NULL OR defDvoa IS NULL OR totalDvoa IS NULL),
                   SUM(ABS(offDvoa) > ? OR ABS(defDvoa) > ? OR ABS(totalDvoa) > ?)
            FROM {t} WHERE {where}""", (self.BOUND,) * 3 + params).fetchone()
        fails = []
        if bad_games:
            fails.append(f"{scope.label}: {bad_games} rows with games != 1 in a one-week request")
        if nulls:
            fails.append(f"{scope.label}: {nulls} rows with a NULL off/def/total DVOA")
        if out_of_range:
            fails.append(f"{scope.label}: {out_of_range} rows with |DVOA| > {self.BOUND}")
        # DVOA is zero-sum across the league by construction; a half-filled or mis-scaled week shows up here.
        mean = conn.execute(f"SELECT AVG(offDvoa) FROM {t} WHERE {where}", params).fetchone()[0]
        if mean is not None and abs(mean) > 0.5:
            fails.append(f"{scope.label}: mean offense DVOA {mean:.3f} is far from the league's ~0")
        return fails


LOADERS = (DvoaTeamLoader,)
