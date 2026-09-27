"""FTN Data loaders (Phase 5). Client and live-verified source facts: fdb/ftn.py.

Every row is placed by its FTN game (gid) through core_ftn_games, never by the feed
it arrived in: FTN files season feeds by CALENDAR at the boundary (the 2024 Super
Bowl, gid 6733, played Feb 2025, sits in the 2025 plays feed). A row whose game
belongs to another season is skipped here (its own season's feed loads it); a gid
FTN's schedule does not know fails the load.
"""
import json

from .. import ftn as api, schedule
from ..loader import Loader, Scope
from .csvbase import WeekCsvLoader


class GamesLoader(Loader):
    """/games/{season}: FTN's schedule. 2020 is loaded too, only so the 2020 Super
    Bowl (in the 2021 calendar feeds) is a known game."""
    id = "ftn.games"
    source = "ftn"
    endpoint = "games"
    table = "core_ftn_games"
    grain = "season"
    ext = "json"
    season_range = (2020, 9999)

    def partition(self, scope):
        return str(scope.season)

    def fetch(self, partition):
        return api.get(f"/games/{partition}")

    def parse(self, payload):
        rows = json.loads(payload) or []
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        bad = [r["gid"] for r in rows if int(r["seas"]) != scope.season]
        if bad:
            raise ValueError(f"{scope.label}: /games/{scope.season} lists games of another season: {bad[:5]}")
        return rows

    def derive(self, row):
        return {"season": self.scope.season}

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def raw_is_final(self, conn, partition):
        return schedule.season_is_closed(conn, int(partition))

    def checks(self, conn, scope):
        """Every FTN game is a schedule game (same season, week, home/away teams through
        team_aliases) and the counts agree."""
        from .nflverse_schedules import CANCELLED_REG
        rows = conn.execute("""
            SELECT g.gid, g.week, s.game_id, ah.team, av.team FROM core_ftn_games g
            JOIN team_aliases ah ON ah.abbr = g.h AND g.season BETWEEN ah.season_from AND ah.season_to
            JOIN team_aliases av ON av.abbr = g.v AND g.season BETWEEN av.season_from AND av.season_to
            LEFT JOIN (SELECT sc.game_id, sc.season, sc.week, h.team ht, a.team at FROM core_schedule sc
                       JOIN team_aliases h ON h.abbr = sc.home_team AND sc.season BETWEEN h.season_from AND h.season_to
                       JOIN team_aliases a ON a.abbr = sc.away_team AND sc.season BETWEEN a.season_from AND a.season_to) s
              ON s.season = g.season AND s.week = g.week AND s.ht = ah.team AND s.at = av.team
            WHERE g.season = ?""", (scope.season,)).fetchall()
        n_ftn = conn.execute("SELECT COUNT(*) FROM core_ftn_games WHERE season = ?", (scope.season,)).fetchone()[0]
        n_sched = conn.execute("SELECT COUNT(*) FROM core_schedule WHERE season = ?", (scope.season,)).fetchone()[0]
        fails = []
        if len(rows) != n_ftn:
            fails.append(f"{scope.label}: {n_ftn - len(rows)} FTN games with a team code no team_aliases row knows")
        # FTN still lists 2022 wk17 BUF @ CIN (gid 6134, 0-0), the no-contest the schedule
        # removed: the SAME named exception (CANCELLED_REG), never a looser count.
        cancelled = {r[0] for r in rows if r[2] is None and {r[3], r[4]} == CANCELLED_REG.get(scope.season)}
        unmatched = [r[0] for r in rows if r[2] is None and r[0] not in cancelled]
        if unmatched:
            fails.append(f"{scope.label}: FTN games with no schedule game (season/week/teams): {unmatched[:8]}")
        if n_ftn - len(cancelled) != n_sched:
            fails.append(f"{scope.label}: FTN lists {n_ftn} games ({len(cancelled)} cancelled), the schedule {n_sched}")
        return fails


class _FtnWeek(WeekCsvLoader):
    """Season feed, loaded one schedule week at a time."""
    source = "ftn"
    ext = "json"
    season_range = (2021, 9999)   # participation is placeholder-only before 2021
    feed = ""

    def fetch(self, partition):
        return api.get_pages(f"/games/{partition}/{self.feed}")

    def parse(self, payload):
        rows = api.flatten(payload)
        return sorted({k for r in rows for k in r}), rows

    def prepare(self, conn):
        super().prepare(conn)
        stype = {(r[0], r[1]): r[2] for r in conn.execute("SELECT DISTINCT season, week, season_type FROM core_schedule")}
        self._games = {r[0]: (r[1], stype.get((r[1], r[2])), r[2]) for r in
                       conn.execute("SELECT gid, season, week FROM core_ftn_games")}

    def row_key(self, row):
        g = self._games.get(row["gid"])
        if g is None:
            raise ValueError(f"FTN gid {row['gid']} is not in core_ftn_games (unknown game)")
        return g

    def derive(self, row):
        return {"season": self.scope.season, "season_type": self.scope.season_type, "week": self.scope.week}

    def raw_is_final(self, conn, partition):
        # Charting is revised for MONTHS (2025 `updated` stamps in Aug 2026): final only
        # once the season is closed - and even then a later refetch is allowed by hand.
        return self._closed(conn, int(partition))


# Named source errata (each found on the first load, 2026-09-27). Rows stay verbatim;
# only the check is told about them.
FTN_PLAY_TEAM_ERRATA = {
    983219: "2022 wk8 SF @ LA (gid 5998) kickoff: FTN writes off='LAC' for the Rams (LA)",
}
# FTN's /games/{season}/plays files these games in ANOTHER season's feed. Every other
# Super Bowl is in its own season's feed, and /participation files this one correctly.
FTN_PLAYS_FEED = {
    (2024, "POST", 22): "2025",   # 2024 Super Bowl KC-PHI, gid 6733, played 2025-02-09
}


class PlaysLoader(_FtnWeek):
    id = "ftn.plays"
    endpoint = "plays"
    table = "core_ftn_plays"
    feed = "plays"
    team_col = "off"

    def partition(self, scope):
        return FTN_PLAYS_FEED.get((scope.season, scope.season_type, scope.week), str(scope.season))

    def checks(self, conn, scope):
        """Stricter than team coverage: every play's off/def must be the two teams of
        ITS OWN game (errata named above), and every team the schedule had playing
        must have offensive plays."""
        where, params = self.scope_where(scope)
        errata = ",".join(str(p) for p in FTN_PLAY_TEAM_ERRATA) or "0"
        bad = conn.execute(f"""
            SELECT p.pid, p.gid, p.off, p.def FROM core_ftn_plays p JOIN core_ftn_games g ON g.gid = p.gid
            WHERE p.season = ? AND p.season_type = ? AND p.week = ? AND p.pid NOT IN ({errata})
              AND ((p.off IS NOT NULL AND p.off NOT IN (g.h, g.v)) OR (p.def IS NOT NULL AND p.def NOT IN (g.h, g.v)))""",
                           params).fetchall()
        fails = [f"{scope.label}: plays whose off/def is not a team of their game: {[tuple(b) for b in bad[:5]]}"] if bad else []
        got = {r[0] for r in conn.execute(f"""SELECT DISTINCT a.team FROM core_ftn_plays p
                 JOIN team_aliases a ON a.abbr = p.off AND p.season BETWEEN a.season_from AND a.season_to
                 WHERE p.{where.replace(' AND ', ' AND p.')} AND p.pid NOT IN ({errata})""", params)}
        sched = {r[0] for r in conn.execute("""SELECT DISTINCT a.team FROM (
                   SELECT home_team t, season FROM core_schedule WHERE season = ? AND season_type = ? AND week = ?
                   UNION SELECT away_team, season FROM core_schedule WHERE season = ? AND season_type = ? AND week = ?) x
                 JOIN team_aliases a ON a.abbr = x.t AND x.season BETWEEN a.season_from AND a.season_to""", params * 2)}
        if sched - got:
            fails.append(f"{scope.label}: scheduled teams with no plays (partial week in the source?): {sorted(sched - got)}")
        if got - sched:
            fails.append(f"{scope.label}: teams that were not scheduled: {sorted(got - sched)}")
        return fails


class ParticipationLoader(_FtnWeek):
    id = "ftn.participation"
    endpoint = "participation"
    table = "core_ftn_participation"
    feed = "participation"

    def checks(self, conn, scope):
        """No team on these rows: completeness is measured against core_ftn_plays (loaded
        first). Every game of the week must be present, and the scrimmage plays (PASS/
        RUSH) of the week must have a participation row."""
        where, params = self.scope_where(scope)
        games_p = {r[0] for r in conn.execute(f"SELECT DISTINCT gid FROM core_ftn_plays WHERE {where}", params)}
        games_x = {r[0] for r in conn.execute(f"SELECT DISTINCT gid FROM core_ftn_participation WHERE {where}", params)}
        fails = []
        if games_p - games_x:
            fails.append(f"{scope.label}: games with plays but no participation (partial week?): {sorted(games_p - games_x)}")
        n, hit = conn.execute("""SELECT COUNT(*), SUM(x.pid IS NOT NULL) FROM core_ftn_plays p
                                 LEFT JOIN core_ftn_participation x ON x.pid = p.pid
                                 WHERE p.season = ? AND p.season_type = ? AND p.week = ? AND p.type IN ('PASS', 'RUSH')""",
                              params).fetchone()
        if n and hit / n < 0.99:
            fails.append(f"{scope.label}: only {hit}/{n} scrimmage plays have participation")
        return fails


class All22Loader(_FtnWeek):
    """/all22/game/{gid}, one request per game of the week. Raw payload =
    {"<gid>": <that game's response exactly as received>, ...}."""
    id = "ftn.all22"
    endpoint = "all22"
    table = "core_ftn_all22"
    season_range = (2026, 9999)   # nflverse participation carries on-field players through 2025

    def partition(self, scope):
        return f"{scope.season}/{scope.season_type}{scope.week:02d}"

    def fetch(self, partition):
        season, rest = partition.split("/")
        st = rest.rstrip("0123456789")
        week = int(rest[len(st):])
        gids = [r[0] for r in self._conn.execute("SELECT gid FROM core_ftn_games WHERE season = ? AND week = ? ORDER BY gid",
                                                 (int(season), week))]
        if not gids:
            raise ValueError(f"{partition}: no FTN games for this week (load ftn.games first)")
        parts = []
        for gid in gids:
            body, _ = api.get(f"/all22/game/{gid}")
            parts.append(f'"{gid}":'.encode() + body)
        return b"{" + b",".join(parts) + b"}", {"url": f"{api.API}/all22/game/<gid>", "gids": ",".join(map(str, gids))}

    def prepare(self, conn):
        super().prepare(conn)
        self._conn = conn

    def parse(self, payload):
        rows = [{**r, "gid": int(gid)} for gid, game in json.loads(payload).items() for r in (game or [])]
        return sorted({k for r in rows for k in r} - {"gid"}), rows

    def scope_rows(self, rows, scope):
        return rows  # the file IS the week

    def derive(self, row):
        return {"season": self.scope.season, "season_type": self.scope.season_type, "week": self.scope.week}

    def raw_is_final(self, conn, partition):
        return self._closed(conn, int(partition.split("/")[0]))

    def checks(self, conn, scope):
        where, params = self.scope_where(scope)
        sched = {r[0] for r in conn.execute("SELECT gid FROM core_ftn_games WHERE season = ? AND week = ?",
                                            (scope.season, scope.week))}
        per = dict(conn.execute(f"SELECT gid, COUNT(*) FROM core_ftn_all22 WHERE {where} GROUP BY gid", params).fetchall())
        fails = []
        missing = sched - set(per)
        if missing:
            fails.append(f"{scope.label}: games with no all-22 rows (not charted yet?): {sorted(missing)}")
        thin = {g: n for g, n in per.items() if n < 100}
        if thin:
            fails.append(f"{scope.label}: games with < 100 all-22 plays (partial?): {thin}")
        return fails


LOADERS = (GamesLoader, PlaysLoader, ParticipationLoader, All22Loader)
