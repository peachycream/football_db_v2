"""nflverse weekly rosters -> core_rosters_weekly, one scope per season (2016-)."""
from collections import defaultdict

from .. import schedule
from ..loader import Scope
from .csvbase import CsvLoader


# Teams that had a roster in a week but no game, each with a reason. Named
# exceptions, never a looser rule (same policy as CANCELLED_REG in the schedule).
ROSTER_NO_GAME = {
    (2020, 4): {"PIT", "TEN"},   # COVID: TEN outbreak, game moved to week 7
    (2020, 5): {"DEN", "NE"},    # COVID: game moved to week 6
    (2022, 17): {"BUF", "CIN"},  # Damar Hamlin: no-contest, removed from the schedule
}
# Rows per team-week include IR, practice squad, cuts. The bound catches a truncated
# or duplicated file, not a roster rule. Observed 2016-2026: 55-122.
ROSTER_ROWS = (40, 130)


class RostersWeeklyLoader(CsvLoader):
    id = "nflverse.rosters_weekly"
    source = "nflverse"
    endpoint = "rosters_weekly"
    table = "core_rosters_weekly"
    grain = "season"
    url_template = "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv"

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
        q = lambda sql, *p: conn.execute(sql, (s, *p)).fetchall()
        # Teams on a week's roster must be exactly the teams the schedule has playing
        # that week (bye teams have no roster row). Compared through team_aliases.
        sched = defaultdict(set)
        for r in q("""SELECT week, a.team FROM (SELECT week, home_team t FROM core_schedule WHERE season = ?
                        UNION SELECT week, away_team FROM core_schedule WHERE season = ?) x
                      JOIN team_aliases a ON a.abbr = x.t AND ? BETWEEN a.season_from AND a.season_to""", s, s):
            sched[r["week"]].add(r["team"])
        ros = defaultdict(set)
        counts = {}
        for r in q("""SELECT week, a.team, COUNT(*) n FROM core_rosters_weekly x
                      JOIN team_aliases a ON a.abbr = x.team AND ? BETWEEN a.season_from AND a.season_to
                      WHERE x.season = ? GROUP BY week, a.team""", s):
            ros[r["week"]].add(r["team"])
            counts[(r["week"], r["team"])] = r["n"]
        for w in sorted(ros):
            extra = ros[w] - sched.get(w, set()) - ROSTER_NO_GAME.get((s, w), set())
            missing = sched.get(w, set()) - ros[w]
            if w in sched and (extra or missing):
                fails.append(f"{s} week {w}: roster teams differ from schedule: extra {sorted(extra)}, missing {sorted(missing)}")
            if w not in sched:
                fails.append(f"{s} week {w}: rosters for a week the schedule does not have")
        lo, hi = ROSTER_ROWS
        odd = [(w, t, n) for (w, t), n in counts.items() if not lo <= n <= hi]
        if odd:
            fails.append(f"{s}: team-weeks with implausible roster rows ({lo}-{hi}): {sorted(odd)[:5]}")
        blank, total = q("SELECT SUM(gsis_id IS NULL), COUNT(*) FROM core_rosters_weekly WHERE season = ?")[0]
        if total and blank / total > 0.01:
            fails.append(f"{s}: {blank}/{total} rows without gsis_id (>1%)")
        unmapped = q("""SELECT DISTINCT team FROM core_rosters_weekly r WHERE season = ? AND NOT EXISTS
                        (SELECT 1 FROM team_aliases a WHERE a.abbr = r.team AND ? BETWEEN a.season_from AND a.season_to)""", s)
        if unmapped:
            fails.append(f"{s}: team values with no team_aliases row: {[r[0] for r in unmapped]}")
        return fails
