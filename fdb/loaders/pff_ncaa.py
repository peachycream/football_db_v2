"""PFF college (league=ncaa) season facets (Phase 14, devy tracker). Client and PFF facts: fdb/pff.py.

One call per facet per season (the bare season call; college has no preseason, which is why the NFL loaders'
week-list workaround is not needed). Probed live 2026-10-10: 2025 passing 1,218 / rushing 3,706 / receiving
5,113 / defense 12,536 / pass rush 9,000 rows. `eligible_season` is PFF's own draft-eligibility year and is what the
tracker shows; PFF re-grades after games, so a season is final only once the NFL season has moved on.
"""
import json

from .. import pff as api, schedule
from ..loader import Loader


class PffNcaaSeasonLoader(Loader):
    source = "pff"
    ext = "json"
    grain = "season"
    season_range = (2025, 2026)
    facet = ""
    key = ""
    min_rows_final = 1
    max_games = 17   # 2025 had 18 players at 16 games (CFP / FCS playoff runs) and one at 17 (an all-star game entry)

    def partition(self, scope):
        return str(scope.season)

    def fetch(self, partition):
        return api.get(f"/v1/facet/{self.facet}", league="ncaa", season=int(partition))

    def parse(self, payload):
        k, rows = api.rows_of(json.loads(payload))
        if k != self.key:
            raise ValueError(f"{self.id}: PFF row list is {k!r}, expected {self.key!r}")
        return sorted({f for r in rows for f in r}), rows

    def scope_rows(self, rows, scope):
        return rows   # the request named the season

    def derive(self, row):
        return {"season": self.scope.season}

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def raw_is_final(self, conn, partition):
        cur = schedule.current_season(conn)
        return cur is not None and int(partition) < cur

    def checks(self, conn, scope):
        n, mx = conn.execute(f"SELECT COUNT(*), MAX(player_game_count) FROM {self.table} WHERE season = ?",
                             (scope.season,)).fetchone()
        floor = self.min_rows_final if self.raw_rec.is_final else 50
        fails = [] if n >= floor else [f"{scope.label}: only {n} players (expected >= {floor}; truncated?)"]
        if mx and mx > self.max_games:
            fails.append(f"{scope.label}: player_game_count {mx} > {self.max_games}")
        return fails


class PassingSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_passing_season"
    endpoint = "ncaa_passing_summary_season"
    table = "core_pff_ncaa_passing_season"
    facet = "passing/summary"
    key = "passing_summary"
    min_rows_final = 800


class RushingSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_rushing_season"
    endpoint = "ncaa_rushing_summary_season"
    table = "core_pff_ncaa_rushing_season"
    facet = "rushing/summary"
    key = "rushing_summary"
    min_rows_final = 2500


class ReceivingSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_receiving_season"
    endpoint = "ncaa_receiving_summary_season"
    table = "core_pff_ncaa_receiving_season"
    facet = "receiving/summary"
    key = "receiving_summary"
    min_rows_final = 3500


class DefenseSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_defense_season"
    endpoint = "ncaa_defense_summary_season"
    table = "core_pff_ncaa_defense_season"
    facet = "defense/summary"
    key = "defense_summary"
    min_rows_final = 8000


class PassRushSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_pass_rush_season"
    endpoint = "ncaa_pass_rush_season"
    table = "core_pff_ncaa_pass_rush_season"
    facet = "defense/pass_rush"
    key = "pass_rush_summary"
    min_rows_final = 6000


LOADERS = (PassingSeason, RushingSeason, ReceivingSeason, DefenseSeason, PassRushSeason)
