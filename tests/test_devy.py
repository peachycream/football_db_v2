"""Phase 14: CFBD loaders, the identity builder, the devy marts and the /devy/ page."""
import csv
import json
import unittest
from unittest import mock

from fdb import devy
from fdb.loaders import cfbd
from tests.helpers import TempEnv


def _usage(i, team, conf, overall=0.5, **kw):
    u = {"overall": overall, "pass": 0.1, "rush": 0.2, "firstDown": 0.3, "secondDown": 0.3, "thirdDown": 0.3,
         "standardDowns": 0.3, "passingDowns": 0.3, **kw}
    return {"season": 2026, "id": i, "name": f"P{i}", "position": "QB", "team": team, "conference": conf, "usage": u}


class Parse(unittest.TestCase):
    def test_usage_duplicate_differing_only_in_conference_collapses_and_keeps_the_filled_one(self):
        rows = [_usage("1", "Troy", ""), _usage("1", "Troy", "SBC"), _usage("2", "Utah", "Big 12")]
        _, out = cfbd.PlayerUsageLoader().parse(json.dumps(rows).encode())
        self.assertEqual(len(out), 2)
        self.assertEqual(next(r for r in out if r["id"] == "1")["conference"], "SBC")
        self.assertEqual(out[0]["usage_overall"], 0.5)

    def test_usage_duplicate_with_different_numbers_is_refused(self):
        rows = [_usage("1", "Troy", "SBC", 0.5), _usage("1", "Troy", "SBC", 0.6)]
        with self.assertRaises(ValueError):
            cfbd.PlayerUsageLoader().parse(json.dumps(rows).encode())

    def test_usage_with_an_unknown_key_is_refused(self):
        r = _usage("1", "Troy", "SBC")
        r["usage"]["newKey"] = 1
        with self.assertRaises(ValueError):
            cfbd.PlayerUsageLoader().parse(json.dumps([r]).encode())

    def test_player_season_keeps_only_the_categories_a_devy_manager_reads(self):
        base = {"season": 2026, "playerId": "1", "player": "A", "position": "QB", "team": "T", "conference": "C", "stat": "1"}
        rows = [{**base, "category": c, "statType": "X"} for c in ("passing", "kicking", "punting", "defensive", "kickReturns")]
        fields, out = cfbd.PlayerSeasonLoader().parse(json.dumps(rows).encode())
        self.assertEqual({r["category"] for r in out}, {"passing", "defensive"})
        self.assertIn("statType", fields)

    def test_a_non_list_payload_is_refused(self):
        with self.assertRaises(ValueError):
            cfbd.RosterLoader().parse(b'{"error": "rate limited"}')

    def test_roster_recruit_ids_are_stored_as_json_text(self):
        _, out = cfbd.RosterLoader().parse(json.dumps([{"id": "1", "team": "T", "recruitIds": [5, 6]}]).encode())
        self.assertEqual(out[0]["recruitIds"], "[5, 6]")


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class Env(TempEnv):
    """A temp DB with a few CFBD rows, a roster of three cells in two leagues, and a temp identity CSV."""

    def __enter__(self):
        super().__enter__()
        self.c = self.conn()
        c = self.c
        lid = c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('t','t','p','h',0)").lastrowid
        stat = [("1", "Ann QB", "QB", "Utah", "passing", "ATT", 100), ("1", "Ann QB", "QB", "Utah", "passing", "COMPLETIONS", 60),
                ("1", "Ann QB", "QB", "Utah", "passing", "YDS", 800), ("1", "Ann QB", "QB", "Utah", "passing", "TD", 8),
                ("2", "Bob RB", "RB", "Texas", "rushing", "CAR", 50), ("2", "Bob RB", "RB", "Texas", "rushing", "YDS", 300),
                ("3", "Cy WR", "WR", "Ohio State", "receiving", "REC", 20), ("3", "Cy WR", "WR", "Ohio State", "receiving", "YDS", 400),
                ("4", "Di WR", "WR", "Ohio State", "receiving", "REC", 30), ("4", "Di WR", "WR", "Ohio State", "receiving", "YDS", 500)]
        c.executemany("INSERT INTO core_cfbd_player_season (season, playerId, player, position, team, conference, category, statType, stat, load_id)"
                      " VALUES (2026,?,?,?,?,'Big Ten',?,?,?,?)", [(*s, lid) for s in stat])
        c.executemany("INSERT INTO core_cfbd_roster (season, id, firstName, lastName, team, weight, height, year, position, load_id) "
                      "VALUES (2026,?,?,?,?,?,?,?,?,?)",
                      [("1", "Ann", "QB", "Utah", 210, 74, 3, "QB", lid), ("2", "Bob", "RB", "Texas", 205, 71, 2, "RB", lid),
                       ("3", "Cy", "WR", "Ohio State", 190, 73, 1, "WR", lid), ("4", "Di", "WR", "Ohio State", 195, 72, 4, "WR", lid)])
        c.executemany("INSERT INTO devy_identity (source_text, position, school_text, cfbd_id, reason) VALUES (?,?,?,?,?)",
                      [("Ann QB", "QB", "Utah", "1", "t"), ("Bob RB", "RB", "Texas", "2", "t"), ("Cy WR", "WR", "OSU", "3", "t"),
                       ("Gone", "WR", "LSU", None, "left college")])
        c.executemany("INSERT INTO app_devy_roster (league_id, franchise_id, franchise_name, line, devy_slot, source_text, position, school_text, seen_on)"
                      " VALUES (?,?,?,?,?,?,?,?,?)",
                      [("L1", "0001", "Mine", 1, 1, "Ann QB", "QB", "Utah", "2026-10-01"),
                       ("L1", "0002", "Other", 1, 1, "Bob RB", "RB", "Texas", "2026-10-01"),
                       ("L1", "0002", "Other", 1, 2, "Gone", "WR", "LSU", "2026-10-01"),
                       ("L2", "0003", "Mine2", 1, 1, "Bob RB", "RB", "Texas", "2026-10-01"),
                       ("L2", "0004", "Two", 1, 1, "Bob RB", "RB", "Texas", "2026-10-01"),
                       ("L2", "0004", "Two", 1, 2, "Cy WR", "WR", "OSU", "2026-10-01")])
        c.executemany("INSERT INTO my_franchises (platform, league_id, season, name, my_franchise) VALUES ('mfl',?,2026,?,?)",
                      [("L1", "League One", "0001"), ("L2", "League Two", "0003")])
        return self


class Marts(unittest.TestCase):
    def test_free_agents_exclude_every_rostered_player_in_that_league_only(self):
        with Env() as e:
            fa = lambda lg: {r[0] for r in e.c.execute("SELECT cfbd_id FROM mart_devy_free_agents WHERE league_id = ? AND season = 2026", (lg,))}
            # L1 rosters players 1 and 2 -> only 3 and 4 are free; L2 rosters 2 and 3 -> 1 and 4 are free
            self.assertEqual(fa("L1"), {"3", "4"})
            self.assertEqual(fa("L2"), {"1", "4"})

    def test_is_mine_comes_from_the_config_franchise_not_a_name(self):
        with Env() as e:
            r = {(x[0], x[1]): x[2] for x in e.c.execute("SELECT league_id, franchise_id, is_mine FROM mart_devy_board WHERE season = 2026 OR season IS NULL")}
            self.assertEqual(r[("L1", "0001")], 1)
            self.assertEqual(r[("L1", "0002")], 0)
            self.assertEqual(r[("L2", "0003")], 1)
            self.assertEqual(r[("L2", "0004")], 0)

    def test_a_skipped_cell_keeps_its_row_with_no_stats(self):
        with Env() as e:
            r = e.c.execute("SELECT cfbd_id, mapping_reason, season FROM mart_devy_board WHERE source_text = 'Gone'").fetchone()
            self.assertIsNone(r[0]); self.assertEqual(r[1], "left college"); self.assertIsNone(r[2])

    def test_rates_are_computed_from_counts_and_age_is_never_invented(self):
        with Env() as e:
            r = e.c.execute("SELECT pass_cmp_pct, pass_ypa, age, height_in, production_score FROM mart_devy_player_season WHERE cfbd_id = '1'").fetchone()
            self.assertAlmostEqual(r[0], 60.0); self.assertAlmostEqual(r[1], 8.0)
            self.assertIsNone(r[2]); self.assertEqual(r[3], 74)
            self.assertAlmostEqual(r[4], 0.04 * 800 + 4 * 8)

    def test_a_player_without_a_cfbd_position_group_is_left_out(self):
        with Env() as e:
            e.c.execute("UPDATE core_cfbd_roster SET position = 'OL' WHERE id = '1'")
            self.assertIsNone(e.c.execute("SELECT 1 FROM mart_devy_player_season WHERE cfbd_id = '1'").fetchone())


class Estimate(unittest.TestCase):
    def test_draft_class_estimate_is_three_years_after_high_school_from_class_year(self):
        with Env() as e:
            # Env classes (2026): Ann 3 (JR) -> 2027, Bob 2 (SO) -> 2028, Cy 1 (FR) -> 2029, Di 4 (SR) -> 2027
            got = dict(tuple(r) for r in e.c.execute("SELECT cfbd_id, draft_class_est FROM mart_devy_player_season WHERE season = 2026"))
            self.assertEqual(got, {"1": 2027, "2": 2028, "3": 2029, "4": 2027})

    def test_a_graduate_class_year_still_estimates_next_year_and_a_missing_class_year_gives_none(self):
        with Env() as e:
            e.c.execute("UPDATE core_cfbd_roster SET year = 6 WHERE id = '1'")
            e.c.execute("UPDATE core_cfbd_roster SET year = NULL WHERE id = '2'")
            got = dict(tuple(r) for r in e.c.execute("SELECT cfbd_id, draft_class_est FROM mart_devy_player_season WHERE season = 2026"))
            self.assertEqual(got["1"], 2027); self.assertIsNone(got["2"])

    def test_pff_link_brings_games_and_its_own_eligibility_year_without_replacing_the_estimate(self):
        with Env() as e:
            lid = e.c.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES ('t','t','p','h',0)").lastrowid
            e.c.execute("INSERT INTO core_pff_ncaa_receiving_season (season, player_id, team_name, franchise_id, player_game_count, eligible_season, "
                        "draft_season, grades_pass_route, load_id) VALUES (2026, 900, 'OHIO ST', 5, 6, 2030, NULL, 81.5, ?)", (lid,))
            e.c.execute("INSERT INTO devy_pff_identity (cfbd_id, pff_id, reason) VALUES ('3', 900, 't')")
            r = e.c.execute("SELECT games, draft_eligible_season, draft_season, draft_class_est, route_grade FROM mart_devy_player_season "
                            "WHERE season = 2026 AND cfbd_id = '3'").fetchone()
            self.assertEqual(tuple(r), (6, 2030, None, 2029, 81.5))
            other = e.c.execute("SELECT games FROM mart_devy_player_season WHERE season = 2026 AND cfbd_id = '4'").fetchone()[0]
            self.assertIsNone(other)   # no link, no PFF numbers

    def test_page_labels_the_estimate_and_shows_pff_eligibility_separately(self):
        with Env() as e:
            e.c.close()
            from app import create_app
            app = create_app(); app.logger.setLevel("CRITICAL")
            html = app.test_client().get("/devy/?league=L1&season=2026&view=fa").get_data(as_text=True)
            self.assertIn("est.", html); self.assertIn("PFF elig.", html)
            self.assertIn("2029", html); self.assertNotIn("2,029", html)   # a year is not a thousands-separated count


class Page(unittest.TestCase):
    def _client(self):
        from app import create_app
        app = create_app(); app.logger.setLevel("CRITICAL")
        return app.test_client()

    def test_board_shows_a_two_owner_player_once_with_both_owners_and_highlights_mine(self):
        with Env() as e:
            e.c.close()
            html = self._client().get("/devy/?league=L2&season=2026").get_data(as_text=True)
            self.assertEqual(html.count("Bob RB"), 1)
            self.assertIn("Mine2", html); self.assertIn("Two", html)
            self.assertIn('class="dv-mine"', html)

    def test_free_agent_view_lists_unrostered_players_and_not_rostered_ones(self):
        with Env() as e:
            e.c.close()
            html = self._client().get("/devy/?league=L1&season=2026&view=fa").get_data(as_text=True)
            self.assertIn("Cy WR", html); self.assertIn("Di WR", html)
            self.assertNotIn("Ann QB", html); self.assertNotIn("Bob RB", html)

    def test_a_bad_league_or_season_falls_back_instead_of_failing(self):
        with Env() as e:
            e.c.close()
            r = self._client().get("/devy/?league=nope&season=1900&pos=XX")
            self.assertEqual(r.status_code, 200)

    def test_api_returns_players_and_the_cell_with_no_cfbd_record(self):
        with Env() as e:
            e.c.close()
            j = self._client().get("/api/devy/board?league=L1&season=2026").get_json()
            self.assertEqual({p["cfbd_id"] for p in j["players"]}, {"1", "2"})
            self.assertEqual([r["source_text"] for r in j["no_cfbd_record"]], ["Gone"])


class Identity(unittest.TestCase):
    def _run(self, e, rows, pff=()):
        a, b = e.dir / "devy_identity.csv", e.dir / "devy_pff_identity.csv"
        _write_csv(a, ["source_text", "position", "school_text", "cfbd_id", "reason"], rows)
        _write_csv(b, ["cfbd_id", "pff_id", "reason"], pff)
        with mock.patch.object(devy, "PATH", a), mock.patch.object(devy, "PFF_PATH", b):
            return devy.build(e.c)

    def test_exact_duplicate_rows_collapse(self):
        with Env() as e:
            res = self._run(e, [("Ann QB", "QB", "Utah", "1", "t"), ("Ann QB", "QB", "Utah", "1", "t"), ("Bob RB", "RB", "Texas", "2", "t"),
                                ("Cy WR", "WR", "OSU", "3", "t"), ("Gone", "WR", "LSU", "", "left")])
            self.assertEqual(res["failures"], [])
            self.assertEqual(e.c.execute("SELECT COUNT(*) FROM devy_identity").fetchone()[0], 4)

    def test_one_cell_approved_as_two_players_is_refused(self):
        with Env() as e:
            res = self._run(e, [("Ann QB", "QB", "Utah", "1", "t"), ("Ann QB", "QB", "Utah", "2", "t")])
            self.assertTrue(any("approved as" in f for f in res["failures"]))

    def test_a_skip_needs_a_reason(self):
        with Env() as e:
            res = self._run(e, [("Ann QB", "QB", "Utah", "", "")])
            self.assertTrue(any("neither an id nor a reason" in f for f in res["failures"]))

    def test_a_stale_cfbd_id_fails_loudly(self):
        with Env() as e:
            res = self._run(e, [("Ann QB", "QB", "Utah", "1", "t"), ("Bob RB", "RB", "Texas", "2", "t"), ("Cy WR", "WR", "OSU", "999", "t"),
                                ("Gone", "WR", "LSU", "", "left")])
            self.assertTrue(any("999" in f for f in res["failures"]))

    def test_a_roster_cell_with_no_approved_row_fails(self):
        with Env() as e:
            res = self._run(e, [("Ann QB", "QB", "Utah", "1", "t")])
            self.assertTrue(any("no approved identity row" in f for f in res["failures"]))

    def test_a_pff_link_for_an_unapproved_cfbd_id_is_refused(self):
        with Env() as e:
            res = self._run(e, [("Ann QB", "QB", "Utah", "1", "t"), ("Bob RB", "RB", "Texas", "2", "t"), ("Cy WR", "WR", "OSU", "3", "t"),
                                ("Gone", "WR", "LSU", "", "left")], pff=[("77", "5", "x")])
            self.assertTrue(any("not in devy_identity" in f for f in res["failures"]))


if __name__ == "__main__":
    unittest.main()
