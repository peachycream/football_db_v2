"""Week-grain nflverse/ffverse loaders (Phase 2). One class per source file family.

Every class maps rows onto the SCHEDULE's (season, season_type, week); three week
vocabularies exist and none is assumed to equal another:
  * nflverse stats/pbp/snaps/ffverse: schedule weeks (POST 18-21 before 2021, 19-22 after)
  * NGS: Super Bowl numbered one week later (skips Pro Bowl week)
  * PFF (Phase 4): 28/29/30/32
"""
from .. import config
from .csvbase import WeekCsvLoader

NV = "https://github.com/nflverse/nflverse-data/releases/download"
POST_GAME_TYPES = {"WC", "DIV", "CON", "SB"}


def _fields(loader_id):
    return [l.strip() for l in (config.CONTRACTS_DIR / f"{loader_id}.fields").read_text().splitlines()
            if l.strip() and not l.startswith("#")]


class PlayerStatsLoader(WeekCsvLoader):
    id = "nflverse.player_stats"
    source, endpoint, table = "nflverse", "player_stats", "core_player_stats"
    url_template = NV + "/stats_player/stats_player_week_{season}.csv"

    def extra_checks(self, conn, scope):
        # Loose per team (CHI 2017 wk7 really threw 7 passes), tight for the league-week.
        where, p = self.scope_where(scope)
        fails = []
        bad = conn.execute(f"""SELECT team, SUM(attempts) a, SUM(carries) c FROM core_player_stats WHERE {where}
                               GROUP BY team HAVING a NOT BETWEEN 3 AND 80 OR c NOT BETWEEN 3 AND 70""", p).fetchall()
        if bad:
            fails.append(f"{scope.label}: implausible team pass attempts / carries: {[tuple(r) for r in bad]}")
        n, avg = conn.execute(f"""SELECT COUNT(*), AVG(a) FROM (SELECT team, SUM(attempts) a FROM core_player_stats
                               WHERE {where} GROUP BY team)""", p).fetchone()
        # Only for full weeks: Super Bowl LII (Brady 48, Foles 43) averages 46.5 on its own.
        if n >= 20 and not 25 <= avg <= 45:
            fails.append(f"{scope.label}: league average pass attempts per team {avg:.1f}, outside 25-45")
        return fails


class SnapCountsLoader(WeekCsvLoader):
    id = "nflverse.snap_counts"
    source, endpoint, table = "nflverse", "snap_counts", "core_snap_counts"
    url_template = NV + "/snap_counts/snap_counts_{season}.csv"

    def row_key(self, row):
        st = "POST" if row["game_type"] in POST_GAME_TYPES else "REG" if row["game_type"] == "REG" else None
        return int(row["season"]), st, int(row["week"])

    def extra_checks(self, conn, scope):
        # v1's mis-map (rule 13a) showed as a LEAGUE-WEEK max of 37 where a real week
        # tops out near 90. Per team stays loose: KC 2024 wk18 rested starters (max 34).
        where, p = self.scope_where(scope)
        fails = []
        wk_max = conn.execute(f"SELECT MAX(offense_snaps) FROM core_snap_counts WHERE {where}", p).fetchone()[0] or 0
        if not 55 <= wk_max <= 110:
            fails.append(f"{scope.label}: league-week max offense_snaps {wk_max}, outside 55-110")
        bad = conn.execute(f"""SELECT team, MAX(offense_snaps) m FROM core_snap_counts WHERE {where}
                               GROUP BY team HAVING m NOT BETWEEN 20 AND 110""", p).fetchall()
        if bad:
            fails.append(f"{scope.label}: team max offense_snaps implausible: {[tuple(r) for r in bad]}")
        return fails


class PbpLoader(WeekCsvLoader):
    id = "nflverse.pbp"
    source, endpoint, table = "nflverse", "pbp", "core_pbp"
    url_template = NV + "/pbp/play_by_play_{season}.csv.gz"
    ext = "csv.gz"
    team_col = "posteam"
    warn_new_fields = False  # 117 of ~372 columns kept on purpose

    @property
    def keep_fields(self):
        return _fields(self.id)

    def extra_checks(self, conn, scope):
        where, p = self.scope_where(scope)
        bad = conn.execute(f"""SELECT game_id, COUNT(*) n FROM core_pbp WHERE {where}
                               GROUP BY game_id HAVING n NOT BETWEEN 120 AND 260""", p).fetchall()
        return [f"{scope.label}: implausible plays per game: {[tuple(r) for r in bad]}"] if bad else []


class ParticipationLoader(WeekCsvLoader):
    id = "nflverse.participation"
    source, endpoint, table = "nflverse", "participation", "core_participation"
    url_template = NV + "/pbp_participation/pbp_participation_{season}.csv"
    season_range = (2016, 2025)  # nflverse: "Season must be between 2016 and 2025"; FTN covers 2026
    team_col = "possession_team"
    warn_new_fields = False      # name/jersey lists deliberately not stored

    def row_key(self, row):
        # Empty shells (no players on either side, no possession team, n_offense 0)
        # are non-play events such as the two-minute warning: 783 of 48,434 rows in
        # 2016, none of them in pbp. They carry no data and are not loaded.
        if not row["offense_players"] and not row["defense_players"]:
            return None
        return self.games.get(row["nflverse_game_id"])  # None (unknown game) -> never in a scope

    def extra_checks(self, conn, scope):
        # Two directions: every participation play must be a pbp play, and pbp's
        # passes/runs must be covered. (A raw count ratio is meaningless: participation
        # also lists non-scrimmage plays.) Skipped when pbp for the week isn't loaded.
        where, p = self.scope_where(scope)
        w_part, _ = self.scope_where(scope, "x")
        w_pbp, _ = self.scope_where(scope, "b")
        n_pbp = conn.execute(f"SELECT COUNT(*) FROM core_pbp WHERE {where}", p).fetchone()[0]
        if not n_pbp:
            return []
        orphan, total = conn.execute(f"""SELECT SUM(NOT EXISTS (SELECT 1 FROM core_pbp b WHERE b.game_id = x.nflverse_game_id
                                                AND b.play_id = x.play_id)), COUNT(*) FROM core_participation x WHERE {w_part}""", p).fetchone()
        covered, plays = conn.execute(f"""SELECT SUM(EXISTS (SELECT 1 FROM core_participation x WHERE x.nflverse_game_id = b.game_id
                                                AND x.play_id = b.play_id)), COUNT(*) FROM core_pbp b
                                          WHERE {w_pbp}
                                          AND (b.pass = 1 OR b.rush = 1)""", p).fetchone()
        fails = []
        if total and orphan / total > 0.01:
            fails.append(f"{scope.label}: {orphan}/{total} participation plays are not in pbp")
        if plays and covered / plays < 0.95:
            fails.append(f"{scope.label}: participation covers only {covered}/{plays} pbp passes/runs")
        return fails


class _NgsLoader(WeekCsvLoader):
    source = "nflverse"
    per_season_file = False
    week_col = "schedule_week"
    team_col = "team_abbr"
    team_coverage = "subset"   # NGS lists qualifying players only

    def prepare(self, conn):
        super().prepare(conn)
        self.sb_week = {r[0]: r[1] for r in conn.execute(
            "SELECT season, MAX(week) FROM core_schedule WHERE game_type = 'SB' GROUP BY season")}

    def row_key(self, row):
        w = int(row["week"])
        if w == 0:
            return None  # season-total sentinel, not a week
        s = int(row["season"])
        if row["season_type"] == "POST" and s in self.sb_week and w == self.sb_week[s] + 1:
            w = self.sb_week[s]  # NGS Super Bowl week -> schedule Super Bowl week
        return s, row["season_type"], w

    def derive(self, row):
        s, st, w = self.row_key(row)
        return {"schedule_week": w}  # season/season_type/week stay NGS's own values


class NgsPassingLoader(_NgsLoader):
    id, endpoint, table = "nflverse.ngs_passing", "ngs_passing", "core_ngs_passing"
    url_template = NV + "/nextgen_stats/ngs_passing.csv.gz"
    ext = "csv.gz"


class NgsReceivingLoader(_NgsLoader):
    id, endpoint, table = "nflverse.ngs_receiving", "ngs_receiving", "core_ngs_receiving"
    url_template = NV + "/nextgen_stats/ngs_receiving.csv.gz"
    ext = "csv.gz"


class NgsRushingLoader(_NgsLoader):
    id, endpoint, table = "nflverse.ngs_rushing", "ngs_rushing", "core_ngs_rushing"
    url_template = NV + "/nextgen_stats/ngs_rushing.csv.gz"
    ext = "csv.gz"


class FfOpportunityLoader(WeekCsvLoader):
    id = "ffverse.ff_opportunity"
    source, endpoint, table = "ffverse", "ff_opportunity", "core_ff_opportunity"
    url_template = "https://github.com/ffverse/ffopportunity/releases/download/latest-data/ep_weekly_{season}.csv"
    team_col = "posteam"
    team_coverage = "subset"

    def row_key(self, row):
        return self.games.get(row["game_id"])

    def derive(self, row):
        return {"season_type": self.row_key(row)[1]}  # season/week are the source's own (= schedule's)

    def extra_checks(self, conn, scope):
        # Rows with player_id NA are ffopportunity's unattributed team bucket: exactly
        # one per team-game at most. (SQLite lets NULL through a PRIMARY KEY, so this
        # is checked here, not left to the key.)
        where, p = self.scope_where(scope)
        bad = conn.execute(f"""SELECT game_id, posteam, COUNT(*) FROM core_ff_opportunity WHERE {where}
                               AND player_id IS NULL GROUP BY 1,2 HAVING COUNT(*) > 1""", p).fetchall()
        return [f"{scope.label}: more than one unattributed row per team-game: {[tuple(r) for r in bad][:3]}"] if bad else []
