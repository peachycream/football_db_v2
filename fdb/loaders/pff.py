"""PFF facet loaders (Phase 4). Client and live-verified source facts: fdb/pff.py.

Weekly facets: one request per (season, week) — `week=N` with PFF's own week number.
PFF numbers the playoffs 28 (wild card), 29 (divisional), 30 (conference), 32 (Super
Bowl); 31 is the Pro Bowl and is never requested. The schedule's POST weeks (18-21 up
to 2020, 19-22 since) are mapped onto that list IN ORDER, never assumed.

Season grades: `week=<every REG week>,28,29,30,32` makes PFF aggregate the REG+POST
window server-side and recompute the grades over it (grades are not additive). The
bare season call is NOT used: it silently includes PRESEASON (v1 measured +16.8%
defensive snaps for 2024).
"""
import json

from .. import pff as api, schedule
from ..loader import Scope
from .csvbase import WeekCsvLoader

PFF_POST_WEEKS = (28, 29, 30, 32)


def post_week_map(conn, season: int) -> dict[int, int]:
    """schedule POST week -> PFF week, for one season."""
    weeks = [r[0] for r in conn.execute("SELECT DISTINCT week FROM core_schedule WHERE season = ? AND season_type = 'POST' "
                                        "ORDER BY week", (season,))]
    if len(weeks) > len(PFF_POST_WEEKS):
        raise ValueError(f"{season}: {len(weeks)} playoff weeks in the schedule; PFF has {len(PFF_POST_WEEKS)}")
    return dict(zip(weeks, PFF_POST_WEEKS))


def pff_week(conn, season: int, season_type: str, week: int) -> int:
    return week if season_type == "REG" else post_week_map(conn, season)[week]


class PffWeekLoader(WeekCsvLoader):
    """One raw file per (season, week). Team checks come from WeekCsvLoader: every
    team the schedule had playing must be present (a partial week in the source),
    and no team that wasn't."""
    source = "pff"
    ext = "json"
    team_col = "team_name"
    facet = ""               # e.g. 'defense/summary'

    def partition(self, scope):
        return f"{scope.season}/{scope.season_type}{scope.week:02d}"

    @staticmethod
    def _split(partition):
        """'2025/REG07' / '2025/POST19' -> (2025, 'REG', 7) / (2025, 'POST', 19)."""
        season, rest = partition.split("/")
        st = rest.rstrip("0123456789")
        return int(season), st, int(rest[len(st):])

    def prepare(self, conn):
        super().prepare(conn)
        self._conn = conn

    def fetch(self, partition):
        season, st, week = self._split(partition)
        return api.get(f"/v1/facet/{self.facet}", league="nfl", season=season,
                       week=pff_week(self._conn, season, st, week))

    def parse(self, payload):
        _, rows = api.rows_of(json.loads(payload))
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        return rows  # the file IS the scope (the request named the week)

    def derive(self, row):
        s = self.scope
        return {"season": s.season, "season_type": s.season_type, "week": s.week,
                "pff_week": pff_week(self._conn, s.season, s.season_type, s.week)}

    def raw_is_final(self, conn, partition):
        # PFF re-grades for weeks after a game (v1 saw 2025 grades revised months
        # later), so only a CLOSED season's weeks are final. In-season weeks are
        # re-fetched every run: ~7 facets x completed weeks, well inside 100 reads/min.
        return schedule.season_is_closed(conn, self._split(partition)[0])


class DefenseWeekLoader(PffWeekLoader):
    id = "pff.defense_week"
    endpoint = "defense_summary"
    table = "core_pff_defense_week"
    facet = "defense/summary"

    def extra_checks(self, conn, scope):
        # Team defensive plays = player snaps / 11. Bounds catch a half-charted game or a
        # duplicated file, not football: a full game is ~50-85 defensive plays.
        where, params = self.scope_where(scope)
        odd = conn.execute(f"""SELECT team_name, SUM(snap_counts_defense) / 11.0 plays FROM {self.table}
                               WHERE {where} GROUP BY team_name HAVING plays < 30 OR plays > 110""", params).fetchall()
        return [f"{scope.label}: implausible defensive plays per team: {[(o[0], round(o[1], 1)) for o in odd]}"] if odd else []


class FgWeekLoader(PffWeekLoader):
    id = "pff.fg_week"
    endpoint = "field_goal_summary"
    table = "core_pff_fg_week"
    facet = "field_goal/summary"
    team_coverage = "subset"   # a team can go a game without a kick attempt


class PassingWeekLoader(PffWeekLoader):
    id = "pff.passing_week"
    endpoint = "passing_summary"
    table = "core_pff_passing_week"
    facet = "passing/summary"


class RushingWeekLoader(PffWeekLoader):
    id = "pff.rushing_week"
    endpoint = "rushing_summary"
    table = "core_pff_rushing_week"
    facet = "rushing/summary"


class ReceivingWeekLoader(PffWeekLoader):
    id = "pff.receiving_week"
    endpoint = "receiving_summary"
    table = "core_pff_receiving_week"
    facet = "receiving/summary"


class BlockingWeekLoader(PffWeekLoader):
    id = "pff.blocking_week"
    endpoint = "offense_blocking"
    table = "core_pff_blocking_week"
    facet = "offense/blocking"


class CoverageSchemeWeekLoader(PffWeekLoader):
    id = "pff.coverage_scheme_week"
    endpoint = "defense_coverage_scheme"
    table = "core_pff_coverage_scheme_week"
    facet = "defense/coverage_scheme"


# PFF rows that break wins <= opportunities <= pass-rush snaps (or sacks <= snaps) AT SOURCE, stored verbatim and
# named here so the check stays strict for every other row. (season, season_type, week, pff id)
PASS_RUSH_ERRATA = {   # the complete list for 2016-2026 wk2: 5 rows in 217 weeks, all 1-2 snap DB/LB rushes
    (2016, "POST", 21, 7864),    # Logan Ryan NE CB (Super Bowl LI): 2 wins on 1 opportunity
    (2018, "REG", 2, 6157),      # Patrick Peterson ARZ CB: 1 win on 0 opportunities
    (2022, "REG", 12, 43645),    # Jake Hansen HST LB: 2 sacks on 1 pass-rush snap
    (2023, "REG", 15, 97340),    # Cameron Mitchell CLV CB: 2 wins on 1 opportunity; PFF's own win rate 200.0
    (2024, "REG", 13, 124326),   # Antonio Johnson JAX S: 2 wins on 1 opportunity; PFF's own win rate 200.0
}


class PassRushWeekLoader(PffWeekLoader):
    """Pass-rush wins/opportunities per rusher-week (REBUILD_DESIGN §6.1 expected sacks).
    The whole-league opportunity count is checked against the defense facet's own
    pass-rush snaps for the same week: the two facets describe the same rushes."""
    id = "pff.pass_rush_week"
    endpoint = "pass_rush_summary"
    table = "core_pff_pass_rush_week"
    facet = "defense/pass_rush"

    def extra_checks(self, conn, scope):
        where, params = self.scope_where(scope)
        fails = []
        bad = [r for r in conn.execute(f"""SELECT season, season_type, week, player_id FROM {self.table} WHERE {where}
                               AND (pass_rush_wins > pass_rush_opp OR pass_rush_opp > snap_counts_pass_rush
                                    OR sacks > snap_counts_pass_rush)""", params) if tuple(r) not in PASS_RUSH_ERRATA]
        if bad:
            fails.append(f"{scope.label}: {len(bad)} rows with wins > opportunities > pass-rush snaps: {[r[3] for r in bad]}")
        mine = conn.execute(f"SELECT SUM(snap_counts_pass_rush) FROM {self.table} WHERE {where}", params).fetchone()[0]
        theirs = conn.execute(f"SELECT SUM(snap_counts_pass_rush) FROM core_pff_defense_week WHERE {where}", params).fetchone()[0]
        if mine and theirs and abs(mine - theirs) > 0.01 * theirs:
            fails.append(f"{scope.label}: pass-rush snaps {mine} vs defense facet {theirs} (>1% apart)")
        return fails

# ------------------------------------------------------------ season grades --
class PffSeasonLoader(PffWeekLoader):
    """Season grain; the week list is every COMPLETED week of the season (all of REG
    + POST once it is closed), mapped to PFF's numbers."""
    grain = "season"
    MIN_ROWS = 400

    def partition(self, scope):
        return str(scope.season)

    def _weeks(self, season):
        return ",".join(str(pff_week(self._conn, season, t, w))
                        for t, w in schedule.completed_weeks(self._conn, season))

    def fetch(self, partition):
        weeks = self._weeks(int(partition))
        if not weeks:
            raise ValueError(f"{partition}: no completed weeks yet")
        return api.get(f"/v1/facet/{self.facet}", league="nfl", season=int(partition), week=weeks)

    def derive(self, row):
        return {"season": self.scope.season, "weeks_requested": self.raw_rec.params["week"]}

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def raw_is_final(self, conn, partition):
        return schedule.season_is_closed(conn, int(partition))

    def checks(self, conn, scope):
        n, max_games = conn.execute(f"SELECT COUNT(*), MAX(player_game_count) FROM {self.table} WHERE season = ?",
                                    (scope.season,)).fetchone()
        weeks = len(self.raw_rec.params["week"].split(","))
        fails = [] if n >= self.MIN_ROWS else [f"{scope.label}: only {n} players (truncated?)"]
        if max_games and max_games > weeks:
            fails.append(f"{scope.label}: player_game_count {max_games} > {weeks} weeks requested (preseason leaked in?)")
        stale = self.raw_rec.params["week"] != self._weeks(scope.season)
        if stale and schedule.season_is_closed(conn, scope.season):
            fails.append(f"{scope.label}: raw was fetched for weeks {self.raw_rec.params['week']}, the closed season has more")
        return fails


class OffenseSeasonLoader(PffSeasonLoader):
    id = "pff.offense_season"
    endpoint = "offense_summary_season"
    table = "core_pff_offense_season"
    facet = "offense/summary"


class DefenseSeasonLoader(PffSeasonLoader):
    id = "pff.defense_season"
    endpoint = "defense_summary_season"
    table = "core_pff_defense_season"
    facet = "defense/summary"


LOADERS = (DefenseWeekLoader, PassRushWeekLoader, FgWeekLoader, PassingWeekLoader, RushingWeekLoader, ReceivingWeekLoader,
           BlockingWeekLoader, CoverageSchemeWeekLoader, OffenseSeasonLoader, DefenseSeasonLoader)
