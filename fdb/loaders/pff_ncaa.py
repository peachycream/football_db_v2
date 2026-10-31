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
    season_range = (2014, 2026)   # Phase 15b: all five facets (15a: defense, pass rush); config.FIRST_SEASON = 2016 is the effective start
    facet = ""
    key = ""
    min_rows_final = 1
    early_min_rows = 1   # floor for seasons <= EARLY_LAST: PFF's early college seasons chart fewer players (2014 defense 6,180 vs 2025 12,536)
    EARLY_LAST = 2018
    season_floor: dict[int, int] = {}   # named per-season floors, each with its reason
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

    # Errata (Phase 15a, probed 2026-10-30): PFF lists one 2017 defender with no team at all ("Unknown 42928", 268 defensive
    # snaps). franchise_id is part of the key, so the row cannot be stored; it is skipped by id and reported, and any other
    # row without a franchise_id fails the load.
    NO_FRANCHISE_ERRATA = {(2017, 42928)}

    def scope_rows(self, rows, scope):
        bad = [r for r in rows if r.get("franchise_id") is None]
        unexplained = [r.get("player_id") for r in bad if (scope.season, r.get("player_id")) not in self.NO_FRANCHISE_ERRATA]
        if unexplained:
            raise ValueError(f"{self.id} {scope.label}: {len(unexplained)} rows with no franchise_id, e.g. player_id {unexplained[:5]}")
        return [r for r in rows if r.get("franchise_id") is not None]   # the request named the season

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
        full = self.season_floor.get(scope.season) or (self.early_min_rows if scope.season <= self.EARLY_LAST else self.min_rows_final)
        floor = full if self.raw_rec.is_final else 50
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
    season_floor = {2020: 700}   # COVID-shortened FBS season: 757 passers vs 794 in 2018 and 948 in 2019


class RushingSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_rushing_season"
    endpoint = "ncaa_rushing_summary_season"
    table = "core_pff_ncaa_rushing_season"
    facet = "rushing/summary"
    key = "rushing_summary"
    min_rows_final = 2500
    season_floor = {2020: 2200}   # COVID-shortened FBS season: 2,373 rushers vs 2,450 in 2018 and 2,892 in 2019


class ReceivingSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_receiving_season"
    endpoint = "ncaa_receiving_summary_season"
    table = "core_pff_ncaa_receiving_season"
    facet = "receiving/summary"
    key = "receiving_summary"
    min_rows_final = 3500
    season_floor = {2020: 3000}   # COVID-shortened FBS season: 3,374 receivers vs 3,374 in 2018 and 4,057 in 2019


class DefenseSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_defense_season"
    endpoint = "ncaa_defense_summary_season"
    table = "core_pff_ncaa_defense_season"
    facet = "defense/summary"
    key = "defense_summary"
    min_rows_final = 8000
    season_range = (2014, 2026)   # Phase 15a: PFF is FBS-wide from 2014 (6,180 rows; 2013 has 1,663, 2010-2012 about 500, 2007 none); config.FIRST_SEASON = 2016 is the effective start
    early_min_rows = 5000
    season_floor = {2020: 7500}   # COVID-shortened FBS season: 7,935 defenders vs 7,852 in 2018 and 9,593 in 2019


class PassRushSeason(PffNcaaSeasonLoader):
    id = "pff.ncaa_pass_rush_season"
    endpoint = "ncaa_pass_rush_season"
    table = "core_pff_ncaa_pass_rush_season"
    facet = "defense/pass_rush"
    key = "pass_rush_summary"
    min_rows_final = 6000
    season_range = (2014, 2026)   # Phase 15a: as defense (2014 4,635 rows)
    early_min_rows = 3500
    season_floor = {2020: 5500}   # COVID-shortened FBS season: 5,879 rushers vs 5,662 in 2018 and 6,936 in 2019


LOADERS = (PassingSeason, RushingSeason, ReceivingSeason, DefenseSeason, PassRushSeason)
