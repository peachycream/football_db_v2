"""Phase 15e-2 backtest, exactly as PHASE15E2_SPEC.md (committed b20c805 before any number here was computed). Read-only.

Usage: python ops/phase15e2_backtest.py [--seed N]
One run. The primary test per position: Spearman(FULL) - Spearman(B0) on pooled out-of-time ppg3, paired-bootstrap two-sided p,
Holm-adjusted over the five positions; ship only if the point estimate > 0 and the adjusted p < 0.05. Everything else here is
descriptive. Population, label, folds and bootstrap are those of ops/phase15e_backtest.py.
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

DB = Path(__file__).resolve().parent.parent / "database" / "fdb.db"
SNAP_FLOOR = 300
TEST_CLASSES = (2020, 2021, 2022, 2023)
FIRST_CLASS, LAST_CLASS = 2017, 2023
GROUPS = ("EDGE", "DT", "LB", "S", "CB")
PFF_TO_GROUP = {"ED": "EDGE", "DI": "DT", "LB": "LB", "CB": "CB", "S": "S"}
GRID = (3.0, 10.0, 30.0, 100.0)
BOOT = 2000

A = ["speed_score", "has_forty", "vertical", "has_vertical", "broad_jump", "has_broad", "cone", "has_cone", "shuttle",
     "has_shuttle", "bench", "has_bench"]
B = {"EDGE": ["pressure_rate", "pr_win_rate", "pr_true_win_rate", "sacks_pg", "c_grade_pass_rush"],
     "DT": ["stops_pg", "c_grade_run_defense", "c_grade_defense", "pr_win_rate", "tackles_pg"],
     "LB": ["stops_pg", "tackles_pg", "box_share", "c_grade_run_defense", "c_grade_coverage"],
     "S": ["c_grade_coverage", "tackles_pg", "slot_share", "fs_share", "tfl_pg"],
     "CB": ["c_grade_coverage", "cov_yards_per_target", "catch_rate_allowed", "pbu_pg", "int_pg"]}
C = ["college_seasons", "left_censored", "age_at_college_season", "has_prev", "p_grade_defense", "p_snaps_defense", "p_games",
     "d_grade_defense", "d_grade_run_defense", "d_grade_coverage", "d_grade_pass_rush", "d_snaps", "d_tackles_pg", "d_sacks_pg",
     "d_tfl_pg"]
D = ["t_group_snaps_prev", "t_group_players_prev", "has_team"]


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    f = pd.read_sql("SELECT * FROM mart_idp_prospect_features WHERE draft_season BETWEEN ? AND ?", c, params=(FIRST_CLASS, LAST_CLASS))
    o = pd.read_sql("""SELECT gsis_id, SUM(points) points, SUM(games) games, SUM(snaps) snaps, MAX(top12) top12_any,
                       MAX(top24) top24_any, MIN(years_observed) yo, SUM(CASE WHEN year_index = 1 THEN snaps END) y1_snaps
                       FROM mart_idp_prospect_outcome GROUP BY gsis_id""", c)
    return f.merge(o, on="gsis_id", how="inner")


def prepare(d):
    d = d[d["yo"] == 3].copy()
    d["group"] = d["nfl_pff_position"].map(PFF_TO_GROUP)
    d = d[d["group"].notna()].copy()
    d["ppg3"] = np.where((d["snaps"] >= SNAP_FLOOR) & (d["games"] > 0), d["points"] / d["games"].replace(0, np.nan), np.nan)
    d["log_pick"] = np.log(d["draft_pick"])
    d["speed_score"] = d["weight_lb"] * 200.0 / d["forty"] ** 4
    for k, c in (("has_vertical", "vertical"), ("has_broad", "broad_jump"), ("has_cone", "cone"), ("has_shuttle", "shuttle"),
                 ("has_bench", "bench")):
        d[k] = d[c].notna().astype(float)
    g = d["c_games"].replace(0, np.nan)
    sn = d["c_snaps_defense"].replace(0, np.nan)
    pg = lambda c: d[c] / g
    d["tackles_pg"], d["tfl_pg"], d["sacks_pg"], d["stops_pg"] = pg("c_tackles"), pg("c_tfl"), pg("c_sacks"), pg("c_stops")
    d["pbu_pg"], d["int_pg"] = pg("c_pass_break_ups"), pg("c_interceptions")
    d["pressure_rate"] = d["c_pressures"] / d["c_snaps_pass_rush"].replace(0, np.nan)
    d["pr_win_rate"] = d["k_pr_wins"] / d["k_pr_opp"].replace(0, np.nan)
    d["pr_true_win_rate"] = d["pr_true_wins"] / d["pr_true_opp"].replace(0, np.nan)
    d["box_share"], d["slot_share"], d["fs_share"] = d["c_snaps_box"] / sn, d["c_snaps_slot"] / sn, d["c_snaps_fs"] / sn
    d["cov_yards_per_target"] = d["c_cov_yards"] / d["c_targets"].replace(0, np.nan)
    d["catch_rate_allowed"] = d["c_receptions"] / d["c_targets"].replace(0, np.nan)
    d["has_prev"] = d["p_season"].notna().astype(float)
    pgp = d["p_games"].replace(0, np.nan)
    d["d_grade_defense"] = d["c_grade_defense"] - d["p_grade_defense"]
    d["d_grade_run_defense"] = d["c_grade_run_defense"] - d["p_grade_run_defense"]
    d["d_grade_coverage"] = d["c_grade_coverage"] - d["p_grade_coverage"]
    d["d_grade_pass_rush"] = d["c_grade_pass_rush"] - d["p_grade_pass_rush"]
    d["d_snaps"] = d["c_snaps_defense"] - d["p_snaps_defense"]
    d["d_tackles_pg"] = d["tackles_pg"] - d["p_tackles"] / pgp
    d["d_sacks_pg"] = d["sacks_pg"] - d["p_sacks"] / pgp
    d["d_tfl_pg"] = d["tfl_pg"] - d["p_tfl"] / pgp
    d["has_team"] = d["t_group_snaps_prev"].notna().astype(float)
    return d


def sets(g):
    base = ["log_pick"]
    return {"P1": base + A, "P2": base + B[g], "P3": base + C, "P4": base + D, "FULL": base + A + B[g] + C + D}


def design(train, test, cols):
    med = train[cols].median()
    a = train[cols].fillna(med).fillna(0.0)
    b = test[cols].fillna(med).fillna(0.0)
    sc = StandardScaler().fit(a)
    return sc.transform(a), sc.transform(b)


def model(kind, alpha):
    return Ridge(alpha=alpha) if kind == "reg" else LogisticRegression(C=1.0 / alpha, max_iter=2000)


def pick_alpha(train, cols, kind):
    """Leave-one-class-out CV inside the training classes only: smallest held-out error over GRID."""
    classes = sorted(train["draft_season"].unique())
    if len(classes) < 2:
        return 30.0
    best, err = GRID[2], np.inf
    for a in GRID:
        e = []
        for k in classes:
            tr, va = train[train["draft_season"] != k], train[train["draft_season"] == k]
            if len(va) == 0 or len(tr) < 20 or (kind != "reg" and (tr[kind].nunique() < 2)):
                continue
            xa, xb = design(tr, va, cols)
            if kind == "reg":
                e.append(float(np.mean((Ridge(alpha=a).fit(xa, tr["ppg3"]).predict(xb) - va["ppg3"]) ** 2)))
            else:
                p = np.clip(model(kind, a).fit(xa, tr[kind]).predict_proba(xb)[:, 1], 1e-6, 1 - 1e-6)
                e.append(float(log_loss(va[kind], p, labels=[0, 1])))
        if e and np.mean(e) < err:
            best, err = a, float(np.mean(e))
    return best


def fit_predict(train, test, cols, kind):
    a = pick_alpha(train, cols, kind)
    xa, xb = design(train, test, cols)
    m = model(kind, a).fit(xa, train["ppg3"] if kind == "reg" else train[kind])
    return m.predict(xb) if kind == "reg" else m.predict_proba(xb)[:, 1]


def rho(a, b):
    return float(spearmanr(a, b)[0])


def boot_diff(y, p_new, p_base, rng):
    n, out = len(y), []
    for _ in range(BOOT):
        i = rng.integers(0, n, n)
        if len(set(y[i])) < 3:
            continue
        out.append(rho(p_new[i], y[i]) - rho(p_base[i], y[i]))
    out = np.array(out)
    p = 2 * min(float((out <= 0).mean()), float((out >= 0).mean()))
    return np.percentile(out, [2.5, 97.5]), min(1.0, max(p, 1.0 / len(out)))


def holm(ps):
    order = sorted(ps, key=ps.get)
    m, adj, run = len(order), {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (m - i) * ps[k]))
        adj[k] = run
    return adj


def main():
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 15
    rng = np.random.default_rng(seed)
    d = prepare(load())
    print(f"players {len(d)}; seed {seed}; groups {d['group'].value_counts().to_dict()}")
    res, pvals, diffs = {}, {}, {}
    for g in GROUPS:
        dg = d[d["group"] == g]
        S = sets(g)
        out = {"y": [], "B0": [], **{k: [] for k in S}, "class": []}
        flag = {t: {"y": [], "B0": [], "FULL": []} for t in ("top12_any", "top24_any")}
        for n in TEST_CLASSES:
            tr, te = dg[dg["draft_season"] < n], dg[dg["draft_season"] == n]
            trl, tel = tr[tr["ppg3"].notna()], te[te["ppg3"].notna()]
            if len(trl) < 30 or len(tel) < 5:
                continue
            out["y"] += list(tel["ppg3"]); out["B0"] += list(-tel["draft_pick"]); out["class"] += list(tel["draft_season"])
            for k, cols in S.items():
                out[k] += list(fit_predict(trl, tel, cols, "reg"))
            for t in flag:
                if tr[t].sum() < 3 or len(tr) < 30:
                    continue
                flag[t]["y"] += list(te[t])
                flag[t]["B0"] += list(fit_predict(tr, te, ["log_pick"], t))
                flag[t]["FULL"] += list(fit_predict(tr, te, S["FULL"], t))
        y = np.array(out["y"])
        res[g] = {k: rho(np.array(out[k]), y) for k in ["B0", *S]}
        ci, p = boot_diff(y, np.array(out["FULL"]), np.array(out["B0"]), rng)
        pvals[g], diffs[g] = p, (res[g]["FULL"] - res[g]["B0"], ci)
        print(f"\n{g}: out-of-time players {len(y)}")
        print("  Spearman vs ppg3: " + "  ".join(f"{k} {v:.3f}" for k, v in res[g].items()))
        print(f"  PRIMARY FULL-B0 {diffs[g][0]:+.3f}  95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]  p {p:.3f}")
        for t, v in flag.items():
            if len(v["y"]) and len(set(v["y"])) == 2:
                yy = np.array(v["y"])
                print(f"  {t}: n {len(yy)} pos {int(yy.sum())}  AUC B0 {roc_auc_score(yy, v['B0']):.3f} FULL {roc_auc_score(yy, v['FULL']):.3f}  "
                      f"Brier B0 {brier_score_loss(yy, v['B0']):.3f} FULL {brier_score_loss(yy, v['FULL']):.3f}")
        lab = dg[dg["ppg3"].notna()]
        xa, _ = design(lab, lab, S["FULL"])
        coef = pd.Series(Ridge(alpha=pick_alpha(lab, S["FULL"], "reg")).fit(xa, lab["ppg3"]).coef_, index=S["FULL"])
        coef = coef.reindex(coef.abs().sort_values(ascending=False).index)
        print("  FULL standardised coefficients (top 8):", ", ".join(f"{k} {v:+.2f}" for k, v in coef.head(8).items()))
        # role diagnostic (descriptive): how much of pick's link to ppg3 runs through year-1 snaps
        z = lab[["log_pick", "y1_snaps", "ppg3"]].dropna()
        if len(z) > 30:
            r_xy, r_xm, r_my = rho(-z["log_pick"], z["ppg3"]), rho(-z["log_pick"], z["y1_snaps"]), rho(z["y1_snaps"], z["ppg3"])
            partial = (r_xy - r_xm * r_my) / np.sqrt(max(1e-9, (1 - r_xm ** 2) * (1 - r_my ** 2)))
            print(f"  role diagnostic: rho(-pick, ppg3) {r_xy:.3f}; controlling year-1 snaps {partial:.3f}")
    adj = holm(pvals)
    print("\nGATE (primary: FULL - B0, Holm-adjusted over five positions; ship if estimate > 0 and adjusted p < 0.05):")
    for g in GROUPS:
        est = diffs[g][0]
        print(f"  {g}: estimate {est:+.3f}, p {pvals[g]:.3f}, Holm-adjusted {adj[g]:.3f} -> {'SHIP' if est > 0 and adj[g] < 0.05 else 'DO NOT SHIP'}")


if __name__ == "__main__":
    main()
