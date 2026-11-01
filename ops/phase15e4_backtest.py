"""Phase 15e-4 backtest, exactly as PHASE15E4_SPEC.md (committed b532647 before any number here was computed). Read-only.

Usage: python ops/phase15e4_backtest.py [--seed N]
One run. The primary test per position: Spearman(PRIMARY-S) - Spearman(B0) against snaps3 (sum of snaps, years 1-3, no floor) on pooled
out-of-time players, paired-bootstrap two-sided p, Holm-adjusted over the five positions; ship only if the point estimate > 0 and the
adjusted p < 0.05. P-C, P-TC and everything else are descriptive. Folds, ridge grid and bootstrap are those of the earlier phases.
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

DB = Path(__file__).resolve().parent.parent / "database" / "fdb.db"
TEST_CLASSES = (2020, 2021, 2022, 2023)
FIRST_CLASS, LAST_CLASS = 2017, 2023
GROUPS = ("EDGE", "DT", "LB", "S", "CB")
PFF_TO_GROUP = {"ED": "EDGE", "DI": "DT", "LB": "LB", "CB": "CB", "S": "S"}
GRID = (3.0, 10.0, 30.0, 100.0)
BOOT = 2000
STARTER_SNAPS = 900
PPG_FLOOR = 300

T = ["log_pick", "t_group_snaps_prev", "t_group_players_prev", "t_nickel_dime_share", "has_nd_share", "rookie_comp"]
C = ["c_grade_defense", "c_snaps_pg", "has_college_block"]


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    f = pd.read_sql("SELECT * FROM mart_idp_prospect_features WHERE draft_season BETWEEN ? AND ?", c, params=(FIRST_CLASS, LAST_CLASS))
    o = pd.read_sql("""SELECT gsis_id, SUM(points) points3, SUM(games) games, SUM(snaps) snaps3, MAX(top12) top12_any,
                       MAX(top24) top24_any, MIN(years_observed) yo FROM mart_idp_prospect_outcome GROUP BY gsis_id""", c)
    s = pd.read_sql("""SELECT season, team, SUM(nickel_snaps + dime_snaps) nd,
                       SUM(base_snaps + nickel_snaps + dime_snaps + other_pers_snaps) tot
                       FROM mart_team_def_scheme_week WHERE source = 'ftn_participation' AND season_type = 'REG' GROUP BY season, team""", c)
    return f.merge(o, on="gsis_id", how="inner"), s


def prepare(d, s):
    d = d[d["yo"] == 3].copy()
    d["group"] = d["nfl_pff_position"].map(PFF_TO_GROUP)
    d = d[d["group"].notna()].copy()
    d["log_pick"] = np.log(d["draft_pick"])
    s = s.assign(share=s["nd"] / s["tot"].replace(0, np.nan))
    sh = {(r.season, r.team): r.share for r in s.itertuples()}
    d["t_nickel_dime_share"] = [sh.get((y - 1, t), np.nan) for y, t in zip(d["draft_season"], d["draft_team"])]
    d["has_nd_share"] = d["t_nickel_dime_share"].notna().astype(float)
    key = d.groupby(["draft_season", "draft_team", "group"])["draft_pick"]
    d["rookie_comp"] = key.rank(method="min").sub(1).where(d["draft_team"].notna(), np.nan)
    d["c_snaps_pg"] = d["c_snaps_defense"] / d["c_games"].replace(0, np.nan)
    d["has_college_block"] = d["c_grade_defense"].notna().astype(float)
    d["y"] = np.sqrt(d["snaps3"])
    d["ppg3"] = np.where((d["snaps3"] >= PPG_FLOOR) & (d["games"] > 0), d["points3"] / d["games"].replace(0, np.nan), np.nan)
    d["starter3"] = (d["snaps3"] >= STARTER_SNAPS).astype(int)
    return d


def sets():
    return {"PRIMARY-S": T, "P-C": ["log_pick"] + C, "P-TC": T + C}


def design(train, test, cols):
    med = train[cols].median()
    a = train[cols].fillna(med).fillna(0.0)
    b = test[cols].fillna(med).fillna(0.0)
    sc = StandardScaler().fit(a)
    return sc.transform(a), sc.transform(b)


def pick_alpha(train, cols):
    """Leave-one-class-out CV inside the training classes only: smallest held-out squared error over GRID."""
    classes = sorted(train["draft_season"].unique())
    if len(classes) < 2:
        return 30.0
    best, err = GRID[2], np.inf
    for a in GRID:
        e = []
        for k in classes:
            tr, va = train[train["draft_season"] != k], train[train["draft_season"] == k]
            if len(va) == 0 or len(tr) < 20:
                continue
            xa, xb = design(tr, va, cols)
            e.append(float(np.mean((Ridge(alpha=a).fit(xa, tr["y"]).predict(xb) - va["y"]) ** 2)))
        if e and np.mean(e) < err:
            best, err = a, float(np.mean(e))
    return best


def fit_predict(train, test, cols):
    xa, xb = design(train, test, cols)
    return Ridge(alpha=pick_alpha(train, cols)).fit(xa, train["y"]).predict(xb)


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
    d = prepare(*load())
    print(f"players {len(d)}; seed {seed}; groups {d['group'].value_counts().to_dict()}")
    S = sets()
    print("PRIMARY-S features:", T)
    pvals, diffs = {}, {}
    for g in GROUPS:
        dg = d[d["group"] == g]
        out = {"snaps3": [], "points3": [], "ppg3": [], "starter3": [], "top12_any": [], "top24_any": [], "B0": [], **{k: [] for k in S}}
        for n in TEST_CLASSES:
            tr, te = dg[dg["draft_season"] < n], dg[dg["draft_season"] == n]
            if len(tr) < 30 or len(te) < 5:
                continue
            for k in ("snaps3", "points3", "ppg3", "starter3", "top12_any", "top24_any"):
                out[k] += list(te[k])
            out["B0"] += list(-te["draft_pick"])
            for k, cols in S.items():
                out[k] += list(fit_predict(tr, te, cols))
        y = np.array(out["snaps3"])
        P = {k: np.array(out[k]) for k in ["B0", *S]}
        res = {k: rho(P[k], y) for k in P}
        ci, p = boot_diff(y, P["PRIMARY-S"], P["B0"], rng)
        pvals[g], diffs[g] = p, (res["PRIMARY-S"] - res["B0"], ci)
        print(f"\n{g}: out-of-time players {len(y)}")
        print("  Spearman vs snaps3: " + "  ".join(f"{k} {v:.3f}" for k, v in res.items()))
        print(f"  PRIMARY-S-B0 {diffs[g][0]:+.3f}  95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]  p {p:.3f}")
        for k in ("P-C", "P-TC"):   # descriptive, uncorrected
            cik, pk = boot_diff(y, P[k], P["B0"], rng)
            print(f"  {k} - B0 {res[k] - res['B0']:+.3f}  95% CI [{cik[0]:+.3f}, {cik[1]:+.3f}]  p {pk:.3f} (descriptive, uncorrected)")
        for t in ("points3", "ppg3"):
            v = np.array(out[t], dtype=float)
            m = ~np.isnan(v)
            print(f"  carry to {t} (n {int(m.sum())}): B0 {rho(P['B0'][m], v[m]):.3f}  PRIMARY-S {rho(P['PRIMARY-S'][m], v[m]):.3f}")
        for t in ("starter3", "top12_any", "top24_any"):
            v = np.array(out[t])
            if len(set(v)) == 2:
                print(f"  {t}: n {len(v)} pos {int(v.sum())}  AUC B0 {roc_auc_score(v, P['B0']):.3f} PRIMARY-S {roc_auc_score(v, P['PRIMARY-S']):.3f}")
        lab = dg
        xa, _ = design(lab, lab, T)
        coef = pd.Series(Ridge(alpha=pick_alpha(lab, T)).fit(xa, lab["y"]).coef_, index=T)
        print("  PRIMARY-S standardised coefficients:", ", ".join(f"{k} {v:+.2f}" for k, v in coef.items()))
        te_all = dg[dg["draft_season"].isin(TEST_CLASSES)]
        print("  coverage in the test classes (n {}): ".format(len(te_all)) + ", ".join(
            f"{k} {te_all[k].notna().mean():.2f}" for k in ("t_group_snaps_prev", "t_nickel_dime_share", "rookie_comp", "c_grade_defense")))
    adj = holm(pvals)
    print("\nGATE (primary: PRIMARY-S - B0 vs snaps3, Holm-adjusted over five positions; ship if estimate > 0 and adjusted p < 0.05):")
    for g in GROUPS:
        est = diffs[g][0]
        print(f"  {g}: estimate {est:+.3f}, p {pvals[g]:.3f}, Holm-adjusted {adj[g]:.3f} -> {'SHIP STAGE 1' if est > 0 and adj[g] < 0.05 else 'DO NOT SHIP'}")


if __name__ == "__main__":
    main()
