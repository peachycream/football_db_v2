"""Phase 15a: nflverse draft_picks / combine loaders and the PFF NCAA era handling (offline fixtures)."""
import json
import unittest
from types import SimpleNamespace

from fdb import registry
from fdb.loader import Scope
from fdb.loaders import LOADERS
from fdb.loaders.nflverse_draft import CombineLoader, DraftPicksLoader
from fdb.loaders.pff_ncaa import DefenseSeason, PassRushSeason
from tests.helpers import TempEnv


def _load_id(c):
    return c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('t','t','p','h',0)").lastrowid


def _picks(c, rows):
    lid = _load_id(c)
    c.executemany("INSERT INTO core_nflverse_draft_picks (season, round, pick, gsis_id, pfr_player_id, cfb_player_id, load_id) "
                  "VALUES (?,?,?,?,?,?,?)", [(*r, lid) for r in rows])


def _combine(c, rows):
    lid = _load_id(c)
    c.executemany("INSERT INTO core_nflverse_combine (season, draft_year, pfr_id, load_id) VALUES (?,?,?,?)",
                  [(*r, lid) for r in rows])


class DraftPicks(unittest.TestCase):
    def _checks(self, rows):
        with TempEnv() as env:
            c = env.conn()
            _picks(c, rows)
            ldr = DraftPicksLoader()
            ldr.MIN_ROWS = 1
            return ldr.checks(c, Scope(0))

    def test_clean_picks_pass(self):
        self.assertEqual(self._checks([(2017, 1, 1, "G1", "P1", "c1"), (2017, 1, 2, "G2", "P2", "c2")]), [])

    def test_a_repeated_id_since_2016_fails(self):
        for col in range(3, 6):
            a = [2017, 1, 1, "G1", "P1", "c1"]
            b = [2018, 2, 3, "G2", "P2", "c2"]
            b[col] = a[col]
            self.assertTrue(self._checks([tuple(a), tuple(b)]), col)

    def test_old_repeats_and_missing_ids_are_not_checked(self):
        rows = [(1990, 1, 1, None, None, None), (1990, 1, 2, None, None, None), (2000, 1, 1, "G", "P", "c"), (2001, 1, 1, "G", "P", "c")]
        self.assertEqual(self._checks(rows), [])

    def test_a_truncated_file_fails(self):
        with TempEnv() as env:
            c = env.conn()
            _picks(c, [(2017, 1, 1, "G1", "P1", "c1")])
            self.assertTrue(any("only 1" in f for f in DraftPicksLoader().checks(c, Scope(0))))


class Combine(unittest.TestCase):
    def _checks(self, picks, combine):
        with TempEnv() as env:
            c = env.conn()
            _picks(c, picks)
            _combine(c, combine)
            ldr = CombineLoader()
            ldr.MIN_ROWS = 1
            return ldr.checks(c, Scope(0))

    PICKS = [(2017, 1, 1, "G1", "P1", "c1")]

    def test_agreeing_draft_year_passes_and_undrafted_rows_are_ignored(self):
        self.assertEqual(self._checks(self.PICKS, [(2017, 2017, "P1"), (2017, None, "P9")]), [])

    def test_draft_year_disagreeing_with_the_exact_join_fails(self):
        self.assertTrue(self._checks(self.PICKS, [(2017, 2018, "P1")]))

    def test_duplicate_pfr_id_in_one_season_fails_but_old_re_entries_do_not(self):
        self.assertTrue(self._checks(self.PICKS, [(2017, 2017, "P1"), (2017, 2017, "P1")]))
        self.assertEqual(self._checks(self.PICKS, [(2005, 2005, "PX"), (2005, 2005, "PX")]), [])

    def test_the_same_id_in_two_seasons_is_a_re_entry_not_a_duplicate(self):
        self.assertEqual(self._checks(self.PICKS, [(2017, 2017, "P1"), (2018, 2017, "P1")]), [])


class Registry(unittest.TestCase):
    def test_new_tables_have_one_owner_each_and_are_weekly(self):
        for lid, table in (("nflverse.draft_picks", "core_nflverse_draft_picks"), ("nflverse.combine", "core_nflverse_combine")):
            self.assertIn(lid, LOADERS)
            registry.assert_owner(lid, table)
            self.assertEqual(LOADERS[lid].table, table)

    def test_contracts_hold_the_source_field_names(self):
        self.assertIn("cfb_player_id", DraftPicksLoader().expected_fields())
        self.assertIn("pfr_id", CombineLoader().expected_fields())


class PffNcaaEra(unittest.TestCase):
    def test_every_pff_ncaa_facet_reaches_back_to_2014(self):   # 15a: defense and pass rush; 15b: the other three
        for cid, cls in LOADERS.items():
            if cid.startswith("pff.ncaa_"):
                self.assertEqual(cls.season_range, (2014, 2026), cid)

    def test_the_one_team_less_2017_defender_is_skipped_and_any_other_is_refused(self):
        ldr = DefenseSeason()
        ok = {"player_id": 1, "franchise_id": 7}
        errata = {"player_id": 42928, "franchise_id": None}
        self.assertEqual(ldr.scope_rows([ok, errata], Scope(2017)), [ok])
        with self.assertRaises(ValueError):
            ldr.scope_rows([ok, errata], Scope(2018))
        with self.assertRaises(ValueError):
            ldr.scope_rows([{"player_id": 5, "franchise_id": None}], Scope(2017))

    def test_row_floor_by_era(self):
        with TempEnv() as env:
            c = env.conn()
            lid = _load_id(c)
            ldr = DefenseSeason()
            ldr.early_min_rows, ldr.season_floor, ldr.min_rows_final = 3, {2020: 2}, 5
            ldr.raw_rec = SimpleNamespace(is_final=True)
            for season, n in ((2018, 3), (2020, 2), (2021, 5), (2021, 4), (2018, 2)):
                c.execute("DELETE FROM core_pff_ncaa_defense_season")
                c.executemany("INSERT INTO core_pff_ncaa_defense_season (season, player_id, franchise_id, team_name, player_game_count, load_id) "
                              "VALUES (?,?,?,?,?,?)", [(season, i, 1, "T", 10, lid) for i in range(n)])
                fails = ldr.checks(c, Scope(season))
                self.assertEqual(bool(fails), (season, n) in ((2021, 4), (2018, 2)), (season, n, fails))

    def test_checked_in_contract_matches_every_season_probed_2014_2025(self):
        # the probe (2026-10-30) found no missing or new field for 2014, 2015, 2016, 2019 in either facet
        for ldr in (DefenseSeason(), PassRushSeason()):
            self.assertIn("player_id", ldr.expected_fields())
            self.assertIn("draft_season", ldr.expected_fields())


if __name__ == "__main__":
    unittest.main()


class RebuildHoldsTest(unittest.TestCase):
    def test_holds_cover_only_named_scopes(self):
        from fdb import rebuild
        from fdb.loader import Scope
        self.assertTrue(rebuild.held("ftn.participation", Scope(2026, "REG", 7)))
        self.assertFalse(rebuild.held("ftn.participation", Scope(2026, "REG", 5)))
        self.assertFalse(rebuild.held("nflverse.draft_picks", Scope(2026, "REG", 7)))


class Phase15bTest(unittest.TestCase):
    def test_backfill_ranges_and_floors(self):
        from fdb.loaders import cfbd, pff_ncaa
        for c in (cfbd.PlayerSeasonLoader, cfbd.PlayerUsageLoader, cfbd.RosterLoader):
            self.assertEqual(c.season_range, (2016, 2026))
        for c in (pff_ncaa.PassingSeason, pff_ncaa.RushingSeason, pff_ncaa.ReceivingSeason):
            self.assertIn(2020, c.season_floor)

    def test_usage_keeps_one_row_per_position(self):
        from fdb.loaders.cfbd import PlayerUsageLoader
        u = {"overall": 0.1, "pass": 0.1, "rush": 0.1, "firstDown": 0, "secondDown": 0, "thirdDown": 0, "standardDowns": 0, "passingDowns": 0}
        base = {"season": 2021, "id": "1", "name": "A", "team": "T", "conference": "C"}
        data = [{**base, "position": "RB", "usage": u}, {**base, "position": "WR", "usage": {**u, "overall": 0.2}}]
        _, rows = PlayerUsageLoader().parse(json.dumps(data).encode())
        self.assertEqual(sorted(r["position"] for r in rows), ["RB", "WR"])
        with self.assertRaises(ValueError):
            PlayerUsageLoader().parse(json.dumps([data[0], {**data[0], "usage": {**u, "overall": 0.9}}]).encode())
