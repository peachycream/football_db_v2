import csv
import unittest
from pathlib import Path
from unittest import mock

from fdb import identity, loader as fw
from fdb.names import name_disagrees, surname_agrees
from tests.helpers import FIXTURES, TempEnv


def insert_csv(conn, table, path, mutate=None):
    decl = {r[1]: r[2] for r in conn.execute(f"PRAGMA table_info({table})")}
    lid = conn.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('fixture','all',?, '', 0)",
                       (str(path),)).lastrowid
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if mutate:
        rows = mutate(rows)
    cols = [c for c in rows[0] if c in decl]
    conn.executemany(f"INSERT INTO {table} ({', '.join(cols)}, load_id) VALUES ({', '.join('?' * (len(cols) + 1))})",
                     [[fw._cast(r[c], decl[c]) for c in cols] + [lid] for r in rows])


def seeded(env, players_mutate=None, dp_mutate=None):
    c = env.conn()
    insert_csv(c, "core_nflverse_players", FIXTURES / "players_traps.csv", players_mutate)
    insert_csv(c, "core_rosters_weekly", FIXTURES / "rosters_traps.csv")
    insert_csv(c, "core_dp_playerids", FIXTURES / "dp_traps.csv", dp_mutate)
    return c


def ids(c, src, gsis):
    return [r[0] for r in c.execute("SELECT source_id FROM player_ids WHERE source=? AND gsis_id=?", (src, gsis))]


class Names(unittest.TestCase):
    def test_disagree(self):
        self.assertTrue(name_disagrees("Fred Williams", {"display_name": "Kevin Smith", "first_name": "Kevin", "last_name": "Smith"}))
        self.assertTrue(name_disagrees("Jake Schum", {"display_name": "Bobby McCray", "first_name": "Bobby", "last_name": "McCray"}))

    def test_same_person_forms_agree(self):
        cases = [("Nickell Robey", "Nickell Robey-Coleman", "Nickell", "Robey-Coleman"),
                 ("John Saint Clair", "John St. Clair", "John", "St. Clair"),
                 ("DJ Moore", "D.J. Moore", "D.J.", "Moore"),
                 ("Amon-Ra St. Brown", "Amon-Ra St. Brown", "Amon-Ra", "St. Brown"),
                 ("Pat Surtain", "Pat Surtain II", "Patrick", "Surtain")]
        for cand, disp, first, last in cases:
            self.assertFalse(name_disagrees(cand, {"display_name": disp, "first_name": first, "last_name": last}), cand)

    def test_nickname_fails_initial_but_keeps_surname(self):
        p = {"display_name": "Andrew Ogletree", "first_name": "Andrew", "last_name": "Ogletree"}
        self.assertTrue(name_disagrees("Drew Ogletree", p))
        self.assertTrue(surname_agrees("Drew Ogletree", p))


class Identity(unittest.TestCase):
    def test_builds_and_traps_pass(self):
        with TempEnv() as env:
            r = identity.build(seeded(env))
            self.assertEqual(r["failures"], [])
            self.assertTrue(r["applied"])

    def test_nflverse_players_beats_weekly_roster(self):
        with TempEnv() as env:
            c = seeded(env); identity.build(c)
            self.assertEqual(ids(c, "pff", "00-0029435"), ["7530"])  # Damaris Johnson, not Dennis's 8070
            q = c.execute("SELECT reason FROM identity_quarantine WHERE source='pff' AND source_id='8070'").fetchone()
            self.assertIsNotNone(q)

    def test_dp_name_errors_quarantined(self):
        with TempEnv() as env:
            c = seeded(env); identity.build(c)
            for mfl in ("12459", "12483", "11361"):
                self.assertIsNone(c.execute("SELECT 1 FROM player_ids WHERE source='mfl' AND source_id=?", (mfl,)).fetchone(), mfl)

    def test_nickname_with_exact_birth_date_accepted(self):
        with TempEnv() as env:
            c = seeded(env); identity.build(c)
            self.assertEqual(ids(c, "mfl", "00-0037292"), ["15916"])  # Drew/Andrew Ogletree
            self.assertEqual(ids(c, "mfl", "00-0039176"), ["17389"])  # CJ/Basil Okoye

    def test_two_mfl_ids_one_human_both_quarantined(self):
        with TempEnv() as env:
            c = seeded(env); identity.build(c)
            self.assertEqual(ids(c, "mfl", "00-0031636"), [])  # Justin Hamilton DT + S entries

    def test_one_id_per_source_per_human(self):
        with TempEnv() as env:
            c = seeded(env); identity.build(c)
            self.assertEqual(identity.checks(c), [])

    def test_broken_source_fails_trap_and_rolls_back(self):
        """If nflverse ever swapped the McGoverns' pff ids, the trap catches it and
        the previous identity tables survive."""
        def swap(rows):
            for r in rows:
                if r["gsis_id"] == "00-0033011": r["pff_id"] = "41714"
                elif r["gsis_id"] == "00-0035679": r["pff_id"] = "10778"
            return rows
        with TempEnv() as env:
            c = seeded(env, players_mutate=swap)
            r = identity.build(c)
            self.assertFalse(r["applied"])
            self.assertTrue(any("McGovern" in f for f in r["failures"]))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)

    def test_override_needs_reason_and_wins(self):
        with TempEnv() as env:
            c = seeded(env)
            ov = Path(env.dir) / "ov.csv"
            ov.write_text("source,source_id,gsis_id,reason,who,date\nmfl,99999,00-0037292,test,t,2026-09-26\n")
            with mock.patch.object(identity, "OVERRIDES_PATH", ov):
                self.assertEqual(identity.build(c)["failures"], [])
                self.assertEqual(ids(c, "mfl", "00-0037292"), ["99999"])
            ov.write_text("source,source_id,gsis_id,reason,who,date\nmfl,99999,00-0037292,,t,2026-09-26\n")
            with mock.patch.object(identity, "OVERRIDES_PATH", ov), self.assertRaises(ValueError):
                identity.build(c)
