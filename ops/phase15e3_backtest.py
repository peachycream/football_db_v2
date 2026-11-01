"""Phase 15e-3 backtest, exactly as PHASE15E3_SPEC.md (committed 9de31eb before any number here was computed). Read-only.

Usage: python ops/phase15e3_backtest.py [--seed N]
One run. The primary test per position: Spearman(PRIMARY) - Spearman(B0) on pooled out-of-time ppg3, paired-bootstrap two-sided p,
Holm-adjusted over the five positions; ship only if the point estimate > 0 and the adjusted p < 0.05. PRIMARY = log pick + block E
(scouting) + block F (recruiting). P-E, P-F, P-G (log pick + one block; G = CFBD college counts) and everything else are descriptive.
Population, label, folds, ridge grid and bootstrap are those of ops/phase15e_backtest.py and ops/phase15e2_backtest.py.
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

E = ["dp_pre_grade", "dp_pre_pos_rank", "reach", "has_scout"]
F = ["rec_stars", "rec_rating", "log_rec_ranking", "has_recruit"]
G = ["cf_tackles_pg", "cf_tfl_pg", "cf_sacks_pg", "cf_hurries_pg", "cf_pd_pg", "has_cfbd_stats"]


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    f = pd.read_sql("SELECT * FROM mart_idp_prospect_features WHERE draft_season BETWEEN ? AND ?", c, params=(FIRST_CLASS, LAST_CLASS))
    o = pd.read_sql("""SELECT gsis_id, SUM(points) points, SUM(games) games, SUM(snaps) snaps, MAX(top12) top12_any,
                       MAX(top24) top24_any, MIN(years_observed) yo
                       FROM mart_idp_prospect_outcome GROUP BY gsis_id""", c)
    return f.merge(o, on="gsis_id", how="inner")


def prepare(d):
    d = d[d["yo"] == 3].copy()
    d["group"] = d["nfl_pff_position"].map(PFF_TO_GROUP)
    d = d[d["group"].notna()].copy()
    d["ppg3"] = np.where((d["snaps"] >= SNAP_FLOOR) & (d["games"] > 0), d["points"] / d["games"].replace(0, np.nan), np.nan)
    d["log_pick"] = np.log(d["draft_pick"])
    d["reach"] = d["draft_pick"] - d["dp_pre_rank"]
    d["has_scout"] = d["dp_pre_grade"].notna().astype(float)
    d["log_rec_ranking"] = np.log(d["rec_ranking"])
    d["has_recruit"] = d["has_recruit"].fillna(0).astype(float)
    d["has_cfbd_stats"] = d["has_cfbd_stats"].fillna(0).astype(float)
    g = d["c_games"].replace(0, np.nan)
    for k in ("tackles", "tfl", "sacks", "hurries", "pd"):
        d[f"cf_{k}_pg"] = d[f"cf_{k}"] / g
    return d


def sets():
    base = ["log_pick"]
    return {"PRIMARY": base + E + F, "P-E": base + E, "P-F": base + F, "P-G": base + G}


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
    S = sets()
    print("PRIMARY features:", len(S["PRIMARY"]), S["PRIMARY"])
    res, pvals, diffs, sub = {}, {}, {}, {}
    for g in GROUPS:
        dg = d[d["group"] == g]
        out = {"y": [], "B0": [], **{k: [] for k in S}, "class": []}
        flag = {t: {"y": [], "B0": [], "PRIMARY": []} for t in ("top12_any", "top24_any")}
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
                flag[t]["PRIMARY"] += list(fit_predict(tr, te, S["PRIMARY"], t))
        y = np.array(out["y"])
        res[g] = {k: rho(np.array(out[k]), y) for k in ["B0", *S]}
        ci, p = boot_diff(y, np.array(out["PRIMARY"]), np.array(out["B0"]), rng)
        pvals[g], diffs[g] = p, (res[g]["PRIMARY"] - res[g]["B0"], ci)
        print(f"\n{g}: out-of-time players {len(y)}")
        print("  Spearman vs ppg3: " + "  ".join(f"{k} {v:.3f}" for k, v in res[g].items()))
        print(f"  PRIMARY-B0 {diffs[g][0]:+.3f}  95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]  p {p:.3f}")
        for k in ("P-E", "P-F", "P-G"):   # descriptive, uncorrected
            cik, pk = boot_diff(y, np.array(out[k]), np.array(out["B0"]), rng)
            print(f"  {k} - B0 {res[g][k] - res[g]['B0']:+.3f}  95% CI [{cik[0]:+.3f}, {cik[1]:+.3f}]  p {pk:.3f} (descriptive, uncorrected)")
        for t, v in flag.items():
            if len(v["y"]) and len(set(v["y"])) == 2:
                yy = np.array(v["y"])
                print(f"  {t}: n {len(yy)} pos {int(yy.sum())}  AUC B0 {roc_auc_score(yy, v['B0']):.3f} PRIMARY {roc_auc_score(yy, v['PRIMARY']):.3f}  "
                      f"Brier B0 {brier_score_loss(yy, v['B0']):.3f} PRIMARY {brier_score_loss(yy, v['PRIMARY']):.3f}")
        lab = dg[dg["ppg3"].notna()]
        xa, _ = design(lab, lab, S["PRIMARY"])
        coef = pd.Series(Ridge(alpha=pick_alpha(lab, S["PRIMARY"], "reg")).fit(xa, lab["ppg3"]).coef_, index=S["PRIMARY"])
        print("  PRIMARY standardised coefficients:", ", ".join(f"{k} {v:+.2f}" for k, v in coef.items()))
        print(f"  coverage in the labelled set (n {len(lab)}): scouted {lab['has_scout'].mean():.2f}, recruit {lab['has_recruit'].mean():.2f}, "
              f"cfbd stats {lab['has_cfbd_stats'].mean():.2f}; rho(-pick, dp_pre_grade) {rho(-lab['draft_pick'][lab['has_scout'] == 1], lab['dp_pre_grade'].dropna()):.3f}")
    adj = holm(pvals)
    print("\nGATE (primary: PRIMARY - B0, Holm-adjusted over five positions; ship if estimate > 0 and adjusted p < 0.05):")
    for g in GROUPS:
        est = diffs[g][0]
        print(f"  {g}: estimate {est:+.3f}, p {pvals[g]:.3f}, Holm-adjusted {adj[g]:.3f} -> {'SHIP' if est > 0 and adj[g] < 0.05 else 'DO NOT SHIP'}")


if __name__ == "__main__":
    main()
