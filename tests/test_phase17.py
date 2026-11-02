"""Phase 17: the RAS loader, its checks, and the exact (year, pick) bridge with its three rejections (synthetic rows, one temp DB)."""
import unittest

from fdb import registry
from fdb.idp_ras import TEAM_CODES, build_bridge
from fdb.loaders import LOADERS
from fdb.loaders.ras import RasMaintableLoader
from tests.helpers import TempEnv

HEADER = "YEAR,PICK,RD,POS,RAS,10YD,20YD,40YD,TEAM\n"


def _load_id(c):
    return c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('t','t','p','h',0)").lastrowid


class Loader(unittest.TestCase):
    def setUp(self):
        self.env = TempEnv()
        self.env.__enter__()
        self.c = self.env.conn()
        self.ld = RasMaintableLoader()

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def _ras(self, year, pick, rd=1, pos="DE", ras=9.0, d10=1.6, d20=2.7, d40=4.6, team="Eagles"):
        self.c.execute("INSERT INTO core_ras_maintable (YEAR, PICK, RD, POS, RAS, YD10, YD20, YD40, TEAM, load_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (year, pick, rd, pos, ras, d10, d20, d40, team, _load_id(self.c)))

    def test_registry_and_contract(self):
        registry.assert_owner("ras.maintable", "core_ras_maintable")
        registry.assert_owner("idp_prospect.ras_bridge", "mart_idp_prospect_ras_bridge")
        self.assertIn("ras.maintable", LOADERS)
        self.assertEqual(LOADERS["ras.maintable"]().expected_fields(), ["YEAR", "PICK", "RD", "POS", "RAS", "10YD", "20YD", "40YD", "TEAM"])
        self.assertFalse(self.ld.fetches)
        self.assertNotIn("ras.maintable", registry.weekly_loaders())

    def test_parse_keeps_source_headers_and_renames_digit_led_columns(self):
        fields, rows = self.ld.parse((HEADER + "2022,13,1,DT,10.00,1.63,2.74,4.78,Eagles\n2025,33,2,LB,9.86,,,,Browns\n").encode())
        self.assertEqual(fields, ["YEAR", "PICK", "RD", "POS", "RAS", "10YD", "20YD", "40YD", "TEAM"])
        self.assertEqual(rows[0]["YD10"], "1.63")
        self.assertNotIn("10YD", rows[0])
        self.assertEqual(rows[1]["YD10"], "")

    def _checks(self):
        self.ld.min_rows = 2
        return self.ld.checks(self.c, None)

    def test_clean_rows_pass(self):
        self._ras(2016, 1)
        self._ras(2026, 2)
        self.assertEqual(self._checks(), [])

    def test_failures(self):
        self._ras(2016, 1)
        self._ras(2026, 2)
        self._ras(2020, 5, d10=1.7, d20=1.6)                       # splits not increasing
        self._ras(2020, 6, ras=11.0)                               # score off the scale
        self._ras(2021, 7)
        self._ras(2021, 7, pos="CB")                               # an unknown duplicated key
        fails = " | ".join(self._checks())
        self.assertIn("not increasing", fails)
        self.assertIn("implausible", fails)
        self.assertIn("not a known exception", fails)

    def test_the_known_duplicate_is_allowed(self):
        self._ras(2016, 169, pos="LB", team="Lions")
        self._ras(2016, 169, pos="CB", team="Buccaneers")
        self._ras(2026, 2)
        self.assertEqual(self._checks(), [])


class Bridge(unittest.TestCase):
    def setUp(self):
        self.env = TempEnv()
        self.env.__enter__()
        self.c = self.env.conn()
        self.lid = _load_id(self.c)

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def _pick(self, season, pick, gsis, team="PHI", position="DE"):
        self.c.execute("INSERT INTO core_nflverse_draft_picks (season, round, pick, team, gsis_id, side, position, load_id) VALUES (?,?,?,?,?,?,?,?)",
                       (season, 1, pick, team, gsis, "D", position, self.lid))

    def _ras(self, year, pick, pos="DE", team="Eagles", ras=9.0):
        self.c.execute("INSERT INTO core_ras_maintable (YEAR, PICK, RD, POS, RAS, YD10, YD20, YD40, TEAM, load_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (year, pick, 1, pos, ras, 1.6, 2.7, 4.6, team, self.lid))

    def _status(self):
        return {r[0]: r[1] for r in self.c.execute("SELECT gsis_id, ras_status FROM mart_idp_prospect_ras_bridge")}

    def _good(self, n=70):
        for i in range(n):
            self._pick(2022, 100 + i, f"OK{i}")
            self._ras(2022, 100 + i)

    def test_exact_key_and_the_rejections(self):
        self._good()
        self._pick(2022, 1, "DUP"); self._ras(2022, 1); self._ras(2022, 1, pos="CB")          # the site lists the pick twice
        self._pick(2022, 2, "TEAM"); self._ras(2022, 2, team="Cowboys")                       # drafted by PHI, the site says Cowboys
        self._pick(2022, 3, "SIDE", position="CB"); self._ras(2022, 3, pos="DT")              # secondary vs front seven
        self._pick(2022, 4, "NONE")                                                           # no RAS row at all
        self._pick(2022, 5, "TWEEN", position="DE"); self._ras(2022, 5, pos="LB")             # DE vs LB is the same side: accepted
        self._pick(2022, 6, "NOSCORE"); self._ras(2022, 6, ras=None)                          # a row with no score is still a row
        r = build_bridge(self.c)
        self.assertEqual(r["failures"], [], r)
        s = self._status()
        self.assertEqual((s["DUP"], s["TEAM"], s["SIDE"], s["NONE"], s["TWEEN"], s["NOSCORE"]),
                         ("duplicate_key", "team_contradiction", "side_contradiction", "no_ras_row", "ok", "ok"))
        row = self.c.execute("SELECT * FROM mart_idp_prospect_ras_bridge WHERE gsis_id IN ('DUP','TEAM','SIDE')").fetchall()
        for x in row:   # a rejected pair carries no RAS value at all
            self.assertTrue(all(x[k] is None for k in ("ras", "ras_yd10", "ras_yd20", "ras_yd40", "ras_pos")))
        ok = self.c.execute("SELECT ras, ras_yd10, ras_yd20, ras_yd40, ras_pos FROM mart_idp_prospect_ras_bridge WHERE gsis_id = 'OK0'").fetchone()
        self.assertEqual(tuple(ok), (9.0, 1.6, 2.7, 4.6, "DE"))

    def test_a_name_never_selects_a_row(self):
        self._good()
        self._pick(2022, 7, "LOST")      # no row for (2022, 7); a row for another pick must not be picked up by position or team
        self._ras(2022, 8)
        build_bridge(self.c)
        self.assertEqual(self._status()["LOST"], "no_ras_row")

    def test_gate_fails_when_too_few_pairs_are_accepted(self):
        for i in range(20):
            self._pick(2022, 100 + i, f"G{i}")
            self._ras(2022, 100 + i, pos="CB") if i < 12 else self._ras(2022, 100 + i)   # 12 side contradictions of 20
        r = build_bridge(self.c)
        self.assertTrue(any("bridge gate" in f for f in r["failures"]), r)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM mart_idp_prospect_ras_bridge").fetchone()[0], 0)   # rolled back

    def test_an_unknown_team_name_fails_the_build(self):
        self._good()
        self._pick(2022, 9, "ODD"); self._ras(2022, 9, team="Whalers")
        r = build_bridge(self.c)
        self.assertTrue(any("Whalers" in f for f in r["failures"]), r)

    def test_team_table_is_complete(self):
        self.assertEqual(len(TEAM_CODES), 32)
        self.assertEqual(len(set(TEAM_CODES.values())), 32)

    def test_bare_database_builds_nothing(self):
        r = build_bridge(self.c)
        self.assertEqual(r["failures"], [])


if __name__ == "__main__":
    unittest.main()
