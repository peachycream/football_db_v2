import unittest

from fdb import loader as fw
from fdb.loader import Scope
from fdb.loaders.nflverse_weekly import FfOpportunityLoader, NgsPassingLoader, ParticipationLoader, SnapCountsLoader


class NgsWeeks(unittest.TestCase):
    def setUp(self):
        self.ld = NgsPassingLoader()
        self.ld.sb_week = {2020: 21, 2024: 22}

    def row(self, season, st, week):
        return {"season": str(season), "season_type": st, "week": str(week)}

    def test_super_bowl_week_maps_to_schedule(self):
        self.assertEqual(self.ld.row_key(self.row(2024, "POST", 23)), (2024, "POST", 22))
        self.assertEqual(self.ld.row_key(self.row(2020, "POST", 22)), (2020, "POST", 21))

    def test_other_weeks_unchanged_and_week0_dropped(self):
        self.assertEqual(self.ld.row_key(self.row(2024, "POST", 21)), (2024, "POST", 21))
        self.assertEqual(self.ld.row_key(self.row(2024, "REG", 5)), (2024, "REG", 5))
        self.assertIsNone(self.ld.row_key(self.row(2024, "REG", 0)))

    def test_ngs_keeps_its_own_week_verbatim(self):
        self.assertEqual(self.ld.derive(self.row(2024, "POST", 23)), {"schedule_week": 22})


class ParticipationShells(unittest.TestCase):
    def test_empty_shell_rows_skipped(self):
        ld = ParticipationLoader()
        ld.games = {"2016_01_CAR_DEN": (2016, "REG", 1)}
        shell = {"nflverse_game_id": "2016_01_CAR_DEN", "offense_players": "", "defense_players": ""}
        play = {"nflverse_game_id": "2016_01_CAR_DEN", "offense_players": "00-1;00-2", "defense_players": "00-3"}
        self.assertIsNone(ld.row_key(shell))
        self.assertEqual(ld.row_key(play), (2016, "REG", 1))

    def test_season_range_stops_at_2025(self):
        self.assertEqual(ParticipationLoader.season_range, (2016, 2025))


class SeasonTypes(unittest.TestCase):
    def test_snap_game_type(self):
        ld = SnapCountsLoader()
        for gt, st in (("REG", "REG"), ("WC", "POST"), ("SB", "POST")):
            self.assertEqual(ld.row_key({"season": "2024", "game_type": gt, "week": "1"})[1], st)

    def test_ffopp_type_from_schedule(self):
        ld = FfOpportunityLoader()
        ld.games = {"2024_19_X_Y": (2024, "POST", 19)}
        self.assertEqual(ld.derive({"game_id": "2024_19_X_Y"}), {"season_type": "POST"})


class Casting(unittest.TestCase):
    def test_list_value_in_numeric_column_names_the_column(self):
        with self.assertRaisesRegex(ValueError, "fg_blocked_list"):
            fw._cast("53;46", "INTEGER", "fg_blocked_list")
