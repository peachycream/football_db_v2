"""Phase 16b Stage 1: the outlook mart's model, ranks, scope rules and checks (synthetic rows; the build itself is checked on the real DB)."""
import math
import random
import unittest

import numpy as np

from fdb import idp_outlook as o
from fdb import registry
from fdb.builders import BUILDERS
from tests.helpers import TempEnv


def _row(gsis, n, group, points_n=100.0, games_n=16, snaps_n=800, age=26.0, dy=2018, actual=None, **kw):
    r = dict(gsis_id=gsis, season_n=n, season_next=n + 1, position_group=group, points_n=points_n, games_n=games_n, snaps_n=snaps_n,
             points_prev=None, games_prev=None, et_gap=None, es_gap=None, age_next=age, draft_year=dy, model=None,
             pred_points_next=None, rank_pred=None, rank_last=0, points_next_actual=actual)
    r.update(kw)
    return r


def _panel(seed=1, per=120, first=2016, last=2024):
    rnd = random.Random(seed)
    rows = []
    for n in range(first, last + 1):
        for g in o.GROUPS:
            for i in range(per):
                pts = rnd.uniform(20, 200)
                nxt = n + 1 <= last
                rows.append(_row(f"{g}{n}_{i}", n, g, points_n=pts, age=rnd.uniform(22, 34),
                                 actual=max(0.0, 0.7 * pts + rnd.gauss(0, 15)) if nxt else None))
    return rows


class Model(unittest.TestCase):
    def test_numpy_ridge_matches_sklearn(self):
        try:
            from sklearn.linear_model import Ridge
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            self.skipTest("sklearn not installed")
        rnd = np.random.default_rng(3)
        x = rnd.normal(size=(200, len(o.FEATURES)))
        x[rnd.random(x.shape) < 0.2] = np.nan
        x[:, 5] = 1.0                       # a constant column
        x[:, 9] = np.nan                    # an all-missing column
        y = rnd.normal(size=200) * 40 + 100
        z, med, mean, scale = o.design_fit(x)
        ic, coef = o.ridge_fit(z, y, 10.0)
        import pandas as pd
        df = pd.DataFrame(x)
        a = df.fillna(df.median()).fillna(0.0)
        sc = StandardScaler().fit(a)
        sk = Ridge(alpha=10.0).fit(sc.transform(a), y)
        self.assertLess(abs(ic - sk.intercept_), 1e-8)
        self.assertLess(np.abs(coef - sk.coef_).max(), 1e-8)
        test = rnd.normal(size=(30, len(o.FEATURES)))
        test[rnd.random(test.shape) < 0.2] = np.nan
        t_sk = sk.predict(sc.transform(pd.DataFrame(test).fillna(df.median()).fillna(0.0)))
        t_me = ic + o.design_apply(test, med, mean, scale) @ coef
        self.assertLess(np.abs(t_sk - t_me).max(), 1e-8)

    def test_spearman_handles_ties(self):
        try:
            from scipy.stats import spearmanr
        except ImportError:
            self.skipTest("scipy not installed")
        a, b = [1, 2, 2, 3, 5, 5, 6], [3, 1, 4, 4, 2, 9, 9]
        self.assertAlmostEqual(o.spearman(a, b), float(spearmanr(a, b)[0]), places=12)

    def test_ranks_share_the_best_position_on_ties(self):
        self.assertEqual(o.best_rank([10, 30, 30, 20]), [4, 1, 1, 3])

    def test_age_bands(self):
        got = [o.age_band(a) for a in (24.99, 25.0, 27.99, 28.0, 30.99, 31.0, None, float("nan"))]
        self.assertEqual(got, ["<25", "25-27", "25-27", "28-30", "28-30", "31+", None, None])

    def test_features_and_indicators(self):
        r = _row("a", 2022, "DT", points_n=160.0, games_n=16, snaps_n=800, age=27.5, dy=2019, points_prev=120.0, games_prev=12,
                 et_gap=8.0, es_gap=None)
        f = dict(zip(o.FEATURES, o.features(r)))
        self.assertEqual((f["ppg_N"], f["games_N"], f["exp_yrs"], f["has_draft_year"]), (10.0, 16.0, 4.0, 1.0))
        self.assertEqual((f["ppg_prev"], f["has_prev"], f["et_gap_pg"], f["has_et"], f["has_es"]), (10.0, 1.0, 0.5, 1.0, 0.0))
        self.assertTrue(math.isnan(f["es_gap_pg"]))
        g = dict(zip(o.FEATURES, o.features(_row("b", 2022, "DT", dy=None, age=None))))
        self.assertTrue(math.isnan(g["age"]) and math.isnan(g["exp_yrs"]) and g["has_draft_year"] == 0.0 and g["has_prev"] == 0.0)


class Assemble(unittest.TestCase):
    def setUp(self):
        self.out, self.models, self.exits, self.fails = o.assemble(_panel())

    def test_only_dt_s_cb_get_a_model(self):
        self.assertEqual(self.fails, [])
        for r in self.out:
            self.assertEqual(r["model"] is not None, r["position_group"] in o.MODEL_GROUPS)
            self.assertEqual(r["rank_pred"] is not None, r["model"] is not None)
        self.assertEqual({m["position_group"] for m in self.models}, set(o.MODEL_GROUPS))

    def test_origin_rule_trains_only_on_earlier_seasons(self):
        for m in self.models:
            self.assertLess(m["last_train_n"], m["season_n"])
        self.assertEqual({r["season_n"] for r in self.out}, set(range(o.FIRST_OUTLOOK_N, 2025)))

    def test_ranks_match_values(self):
        for g in ("DT", "DE"):
            rows = [r for r in self.out if r["season_n"] == 2022 and r["position_group"] == g]
            top = min(rows, key=lambda r: r["rank_last"])
            self.assertEqual(top["points_n"], max(r["points_n"] for r in rows))
            self.assertEqual(top["rank_last"], 1)
        rows = [r for r in self.out if r["season_n"] == 2022 and r["position_group"] == "DT"]
        best = max(rows, key=lambda r: r["pred_points_next"])
        self.assertEqual(best["rank_pred"], 1)

    def test_a_season_without_a_closed_next_has_no_actual_and_the_prediction_is_made(self):
        newest = [r for r in self.out if r["season_n"] == 2024]
        self.assertTrue(all(r["points_next_actual"] is None for r in newest))
        self.assertTrue(all(r["pred_points_next"] is not None for r in newest if r["position_group"] == "S"))

    def test_the_prediction_tracks_the_signal(self):
        rows = [r for r in self.out if r["season_n"] == 2023 and r["position_group"] == "CB"]
        rho = o.spearman([r["pred_points_next"] for r in rows], [r["points_next_actual"] for r in rows])
        self.assertGreater(rho, 0.6)

    def test_exit_counts(self):
        self.assertTrue(self.exits)
        for n, g, band, cnt, zero in self.exits:
            self.assertIn(band, o.AGE_BANDS)
            self.assertTrue(0 <= zero <= cnt)

    def test_too_little_training_data_is_a_failure_not_a_silent_skip(self):
        rows = [r for r in _panel(per=2) if r["season_n"] <= 2022]
        _, models, _, fails = o.assemble(rows)
        self.assertEqual(models, [])
        self.assertTrue(any("not enough" in f for f in fails))


class Build(unittest.TestCase):
    def test_registry_and_builder(self):
        for t in ("mart_idp_outlook", "mart_idp_outlook_model", "mart_idp_outlook_exit"):
            registry.assert_owner("idp_outlook.build", t)
        self.assertIn("idp_outlook.build", BUILDERS)

    def test_a_bare_database_builds_nothing_and_does_not_fail(self):
        with TempEnv() as env:
            c = env.conn()
            r = o.build(c)
            self.assertEqual(r["failures"], [])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM mart_idp_outlook").fetchone()[0], 0)

    def test_checks_catch_inconsistent_rows(self):
        cols = o.OUTLOOK_COLS
        with TempEnv() as env:
            c = env.conn()
            good = _row("g1", 2022, "DT", rank_last=1, actual=50.0)
            bad = _row("g2", 2022, "DT", rank_last=1, actual=None, season_next=2023)   # next season closed but no actual
            for r in (good,):
                c.execute(f"INSERT INTO mart_idp_outlook ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(r[k] for k in cols))
            self.assertEqual(o.checks(c, {2021, 2022, 2023}), [])
            c.execute(f"INSERT INTO mart_idp_outlook ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(bad[k] for k in cols))
            self.assertTrue(any("points_next_actual" in f for f in o.checks(c, {2021, 2022, 2023})))


if __name__ == "__main__":
    unittest.main()
