"""Flex-position dashboard (fdb/flex_report.py): slot arithmetic on a tiny in-memory DB, and the file write."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fdb import flex_report


def _con():
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE mart_mfl_lineup_size (league_id, season, name, teams, pool_unit, rosters_per_player, pool_teams,
                                       total_starters, idp_starters, off_starters);
    CREATE TABLE mart_mfl_position_slots (league_id, season, position, min_slots, max_slots);
    CREATE TABLE mart_mfl_player_games (season, league_id, mfl_id, position, games, points, through_week);
    INSERT INTO mart_mfl_lineup_size VALUES ('L', 2026, 'Test', 8, 'DIVISION', 2, 8, 5, 0, 5);
    INSERT INTO mart_mfl_position_slots VALUES ('L',2026,'QB',1,1),('L',2026,'RB',1,3),('L',2026,'WR',2,4),('L',2026,'TE',0,1);
    INSERT INTO mart_mfl_player_games VALUES (2026,'L','a','RB',4,40,5),(2026,'L','b','WR',0,0,5);
    """)
    return c


class FlexReport(unittest.TestCase):
    def test_slots_and_teams(self):
        (lg,) = flex_report.build(_con())
        self.assertEqual(lg["teams"], 4)                       # pool 8 / 2 owners per player
        off = lg["groups"]["Offense"]
        self.assertEqual((off["min_sum"], off["flex"]), (4, 1))  # 5 starters - (1+1+2+0)
        self.assertEqual(off["eligible"], ["RB", "WR", "TE"])    # QB 1-1 is fixed
        self.assertEqual(lg["players"], {"RB": [[4, 10.0]]})     # PPG at read time; a 0-game row is dropped

    def test_write_keeps_old_page_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x" / "f.html"
            path, _ = flex_report.write(_con(), out)
            self.assertIn("Chart", path.read_text(encoding="utf-8"))
            bad = _con()
            bad.execute("DELETE FROM mart_mfl_player_games")
            with self.assertRaises(RuntimeError):
                flex_report.write(bad, out)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
