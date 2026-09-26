"""Shared plumbing for loaders whose source is a CSV file over HTTP."""
import csv
import gzip
import io

from .. import http
from ..loader import Loader, Scope


class CsvLoader(Loader):
    ext = "csv"
    url_template = ""  # may contain {season}
    keep_fields: list[str] | None = None  # store only these (large sources); None = all

    def url(self, partition: str) -> str:
        return self.url_template.format(season=partition)

    def fetch(self, partition):
        u = self.url(partition)
        return http.get(u), {"url": u}

    def parse(self, payload: bytes):
        if payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        if self.keep_fields:  # prune while reading: a full pbp season as dicts is >1 GB
            keep = [f for f in self.keep_fields if f in (reader.fieldnames or [])]
            rows = [{k: r[k] for k in keep} for r in reader]
        else:
            rows = list(reader)
        return list(reader.fieldnames or []), rows


class SnapshotCsvLoader(CsvLoader):
    """A whole-file, current-state feed: one scope, never final, re-fetched every run."""
    grain = "snapshot"

    def partition(self, scope):
        return "all"

    def scope_rows(self, rows, scope):
        return rows

    def scope_where(self, scope):
        return "1 = 1", ()

    def raw_is_final(self, conn, partition):
        return False


class WeekCsvLoader(CsvLoader):
    """Week-grain source. The framework offers only COMPLETE weeks (per the schedule);
    this class maps each source row to the schedule's (season, season_type, week)
    and checks that the teams in a loaded week are the teams the schedule had playing."""
    grain = "week"
    per_season_file = True
    week_col = "week"          # table column holding the SCHEDULE week
    team_col = "team"          # source column naming the row's team
    team_coverage = "exact"    # 'exact': every scheduled team present; 'subset': none unscheduled

    def partition(self, scope):
        return str(scope.season) if self.per_season_file else "all"

    def prepare(self, conn):
        from .. import schedule
        self._sched = schedule
        self.games = {r[0]: (r[1], r[2], r[3]) for r in
                      conn.execute("SELECT game_id, season, season_type, week FROM core_schedule")}

    def row_key(self, row):
        """-> (season, season_type, schedule_week) or None to skip the row."""
        return int(row["season"]), row["season_type"], int(row["week"])

    def scope_rows(self, rows, scope):
        want = (scope.season, scope.season_type, scope.week)
        return [r for r in rows if self.row_key(r) == want]

    def derive(self, row):
        season, st, week = self.row_key(row)
        return {"season": season, "season_type": st, self.week_col: week}

    def scope_where(self, scope, alias: str = ""):
        a = f"{alias}." if alias else ""
        return (f"{a}season = ? AND {a}season_type = ? AND {a}{self.week_col} = ?",
                (scope.season, scope.season_type, scope.week))

    def raw_is_final(self, conn, partition):
        return partition != "all" and self._closed(conn, int(partition))

    @staticmethod
    def _closed(conn, season):
        from .. import schedule
        return schedule.season_is_closed(conn, season)

    def checks(self, conn, scope):
        where, params = self.scope_where(scope)
        got = {r[0] for r in conn.execute(f"""SELECT DISTINCT a.team FROM {self.table} x
                 JOIN team_aliases a ON a.abbr = x.{self.team_col} AND x.season BETWEEN a.season_from AND a.season_to
                 WHERE {where}""", params)}
        raw_teams = {r[0] for r in conn.execute(f"SELECT DISTINCT {self.team_col} FROM {self.table} WHERE {where}", params)}
        sched = {r[0] for r in conn.execute("""SELECT DISTINCT a.team FROM (
                   SELECT home_team t, season FROM core_schedule WHERE season = ? AND season_type = ? AND week = ?
                   UNION SELECT away_team, season FROM core_schedule WHERE season = ? AND season_type = ? AND week = ?) x
                 JOIN team_aliases a ON a.abbr = x.t AND x.season BETWEEN a.season_from AND a.season_to""",
                 (scope.season, scope.season_type, scope.week) * 2)}
        fails = []
        unmapped = raw_teams - {None} - {t for t in raw_teams if t and conn.execute(
            "SELECT 1 FROM team_aliases WHERE abbr = ? AND ? BETWEEN season_from AND season_to", (t, scope.season)).fetchone()}
        if unmapped:
            fails.append(f"{scope.label}: team values with no team_aliases row: {sorted(unmapped)}")
        if got - sched:
            fails.append(f"{scope.label}: teams that were not scheduled: {sorted(got - sched)}")
        if self.team_coverage == "exact" and sched - got:
            fails.append(f"{scope.label}: scheduled teams missing (partial week in the source?): {sorted(sched - got)}")
        return fails + self.extra_checks(conn, scope)

    def extra_checks(self, conn, scope):
        return []
