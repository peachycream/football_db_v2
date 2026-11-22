"""IDP start/sit analysis (fdb/idp_start.py): scoring resolution, trend rule, shrinkage, split-half, projection
ordering, and the point-in-time rule (a table as of week W never reads week >= W). Synthetic data only."""
import unittest

import numpy as np
import pandas as pd

from fdb import idp_start as I
from fdb.scoring import Rule


def _frame(players=40, weeks=10, seed=3):
    """Synthetic player-games with the columns load_frame produces: two positions, snap share, tier points."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(players):
        pos = "LB" if i % 2 else "DE"
        skill = rng.normal(1, .3)
        for w in range(1, weeks + 1):
            pct = float(np.clip(0.6 + 0.2 * rng.standard_normal(), .3, 1))
            snaps = int(pct * 65)
            st = max(0.0, skill * snaps * 0.12 + rng.normal(0, 2))
            se = max(0.0, snaps * 0.04 + rng.normal(0, 2))
            vo = float(rng.choice([0, 0, 0, 10, 20]))
            rows.append({"season": 2026, "week": w, "gsis_id": f"g{i}", "mfl_id": f"m{i}", "name": f"P{i}", "pos": pos,
                         "team": "AAA", "defense_snaps": snaps, "defense_pct": pct, "tier_stable": st, "tier_semi": se,
                         "tier_volatile": vo, "total": st + se + vo,
                         **{"pts_" + k: 0.0 for k in I.CAT_KEYS}})
    return pd.DataFrame(rows)


REL = {"games_mean": 12.0, "all": {"tier:stable": {"r_full": .5}, "tier:semi": {"r_full": .3}, "tier:volatile": {"r_full": .2}}}


class Scoring(unittest.TestCase):
    def test_event_resolution_knows_both_tackle_vocabularies(self):
        r30590 = {"DT": {"TK": [Rule("0-99", "*5"), Rule("0-99", "*4")], "AS": [Rule("0-99", "*3.5")]}}
        r46276 = {"DT": {"TKD": [Rule("0-99", "*3")], "ASD": [Rule("0-99", "*2.5")]}}
        self.assertEqual(sum(x.points(2) for x in I._event_rules(r30590, "DT", "tackles")), 18)   # additive rows
        self.assertEqual(sum(x.points(2) for x in I._event_rules(r46276, "DT", "tackles")), 6)
        self.assertEqual(sum(x.points(2) for x in I._event_rules(r46276, "DT", "assists")), 5)
        self.assertEqual(I._event_rules(r46276, "DT", "qb_hits"), [])                               # unscored, not guessed

    def test_every_stat_column_belongs_to_exactly_one_category_and_tier(self):
        cols = [c for _k, _l, _t, cs in I.CATS for c in cs]
        self.assertEqual(len(cols), len(set(cols)))
        self.assertEqual(set(cols), set(I.EVENTS))
        self.assertEqual({t for _k, _l, t, _c in I.CATS}, set(I.TIERS))


class LeagueRules(unittest.TestCase):
    def test_narrowest_group_wins_but_catch_all_always_applies(self):
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE mart_mfl_rules (league_id, season, positions, event, "range", points)')
        allp = "QB|RB|WR|TE|DT|DE|LB|CB|S"
        c.executemany("INSERT INTO mart_mfl_rules VALUES ('L',2026,?,?,?,?)",
                      [(allp, "TK", "0-99", "*4"), ("CB", "TK", "0-99", "*1"), ("S|CB", "TK", "0-99", "*.75")])
        rules, _ = I.league_rules(c, "L")
        pts = lambda pos: sum(r.points(1) for r in I._event_rules(rules, pos, "tackles"))
        self.assertEqual(pts("CB"), 5.0)      # 4 + CB-only 1; the shared S|CB row is not added
        self.assertEqual(pts("S"), 4.75)      # no S-only row, so S|CB applies
        self.assertEqual(pts("LB"), 4.0)


class Table(unittest.TestCase):
    def test_trend_rule(self):
        df = _frame(players=12)
        df.loc[df.gsis_id == "g0", "defense_pct"] = [.5] * 7 + [.8] * 3          # +30 pts: up
        df.loc[df.gsis_id == "g2", "defense_pct"] = [.9] * 7 + [.6] * 3          # -30 pts: down
        df.loc[df.gsis_id == "g4", "defense_pct"] = [.7] * 10                    # flat
        rows = {r["gsis_id"]: r for r in I.player_table(df, 11, REL)}
        self.assertEqual(rows["g0"]["trend"], "up")
        self.assertEqual(rows["g2"]["trend"], "down")
        self.assertEqual(rows["g4"]["trend"], "flat")
        self.assertAlmostEqual(rows["g0"]["snap_delta"], .3, places=6)

    def test_trend_needs_enough_games(self):
        df = _frame(players=4, weeks=10)
        rows = {r["gsis_id"]: r for r in I.player_table(df[df.week <= 4], 5, REL)}
        self.assertTrue(all(r["trend"] == "new" and r["snap_delta"] is None for r in rows.values()))

    def test_point_in_time(self):
        """A table as of week W is identical whatever happens at W or later."""
        df = _frame()
        a = I.player_table(df, 6, REL)
        later = df.copy()
        later.loc[later.week >= 6, ["total", "tier_stable", "tier_volatile", "defense_pct"]] = [999, 999, 999, .01]
        b = I.player_table(later, 6, REL)
        self.assertEqual([(r["gsis_id"], r["proj"], r["ppg"], r["trend"]) for r in a],
                         [(r["gsis_id"], r["proj"], r["ppg"], r["trend"]) for r in b])

    def test_recency_weights_normalise(self):
        self.assertAlmostEqual(I._weighted([1, 1, 1, 1, 1]), 1.0)
        self.assertAlmostEqual(I._weighted([0, 0, 0, 10]), 4.0)                # newest game carries 0.4
        self.assertAlmostEqual(I._weighted([10]), 10.0)                        # one game: weights renormalise
        self.assertIsNone(I._weighted([]))

    def test_shrinkage_pulls_a_hot_player_toward_the_position(self):
        df = _frame(players=30)
        hot = df.gsis_id == "g0"
        df.loc[hot, "tier_volatile"] = 40.0                                     # a hot volatile streak
        rows = {r["gsis_id"]: r for r in I.player_table(df, 11, REL)}
        raw_vol = 40.0 * 10 / df[hot]["defense_snaps"].sum() * rows["g0"]["exp_snaps"]
        self.assertLess(rows["g0"]["proj_tier"]["volatile"], raw_vol)           # shrunk
        self.assertGreater(rows["g0"]["proj_tier"]["volatile"], 0)

    def test_k_from_reliability(self):
        self.assertAlmostEqual(I.shrink_k(REL, "stable"), 12.0)                 # 12*(1-.5)/.5
        low = {"games_mean": 12.0, "all": {"tier:volatile": {"r_full": -0.3}}}
        self.assertAlmostEqual(I.shrink_k(low, "volatile"), 12 * .95 / .05)    # clipped at .05, never infinite

    def test_style_quartiles(self):
        rows = [{"in_pool": True, "stable_share": s / 10} for s in range(1, 11)]
        I.style_labels(rows)
        self.assertEqual(rows[0]["style"], "Big-play")
        self.assertEqual(rows[-1]["style"], "Floor")
        self.assertEqual(rows[4]["style"], "Balanced")


class Stability(unittest.TestCase):
    def test_split_half_recovers_a_real_signal_and_not_noise(self):
        rng = np.random.default_rng(1)
        rows = []
        for i in range(120):
            skill = rng.normal(0, 1)
            for w in range(1, 13):
                snaps = 50
                rows.append({"season": 2025, "week": w, "gsis_id": f"g{i}", "pos": "LB", "defense_snaps": snaps,
                             "defense_pct": .6, "total": 0.0,
                             "tier_stable": 20 + 4 * skill + rng.normal(0, 3),     # persistent skill
                             "tier_semi": 10 + rng.normal(0, 3),                   # pure noise
                             "tier_volatile": 5.0, **{"pts_" + k: 0.0 for k in I.CAT_KEYS}})
        rel = I.split_half(pd.DataFrame(rows), (2025,))
        self.assertGreater(rel["all"]["tier:stable"]["r_full"], .8)
        self.assertLess(abs(rel["all"]["tier:semi"]["r_full"]), .35)
        self.assertIsNone(rel["all"]["tier:volatile"]["r_full"])                  # constant column: undefined, not 0

    def test_json_clean(self):
        out = I._clean({"a": np.float64("nan"), "b": [np.int64(3), np.float64(1.5)], "c": float("inf"), "d": np.bool_(True)})
        self.assertEqual(out, {"a": None, "b": [3, 1.5], "c": None, "d": True})


if __name__ == "__main__":
    unittest.main()
