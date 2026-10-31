"""Phase 15e: position-specific IDP prospect models and a rolling-origin backtest. Read-only; stores nothing.

Usage: python ops/phase15e_backtest.py [--seed N]

SPEC, FIXED BEFORE THE FIRST RUN (REBUILD_LOG Phase 15e; no tuning afterwards, a failed gate is reported as failed):
  Population  mart_idp_prospect_features x mart_idp_prospect_outcome, draft classes 2017-2023 (the classes with all three NFL
              years observed). Position group from players.pff_position: DI -> DT, ED -> EDGE, LB, CB, S. A player with no PFF NFL
              position, or one that is not a defender position, is excluded and counted (no inference from the draft table).
  Label       ppg3 = sum(points) / sum(games) over years 1-3, defined only when years 1-3 hold >= SNAP_FLOOR defensive snaps;
              a player below the floor has no ppg3 (excluded from Spearman and from the fit, counted per group).
              top12_any / top24_any = a finish <= 12 / <= 24 within the NFL position group in ANY of years 1-3 (0 for a player
              who never played), points of league 30590 catch-all, from mart_idp_prospect_outcome.
  Models      B0 = draft slot only (prediction = -pick; logistic on log pick for the flags);
              B1 = log pick + age at draft + height + weight + speed score (weight*200/forty^4) + has_forty;
              M  = B1 + college rates (below). Ridge (alpha = 10) on standardised features, medians from the TRAINING fold fill
              a missing value (an indicator is a feature); logistic ridge (C = 0.1) for the flags. Fixed, never tuned.
  Validation  rolling origin by draft class: test class N in 2020..2023, train on classes 2017..N-1. Pooled over the test
              classes. (The labels of class N-1 finish after draft N: a retrospective, not a live, backtest.)
  Gate        for each position: Spearman(M) - Spearman(B0) on pooled out-of-time ppg3, paired bootstrap over players
              (BOOT draws, 95% percentile interval); shipped only if the lower bound is > 0. Else ship nothing for that position.
"""
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

DB = Path(__file__).resolve().parent.parent / "database" / "fdb.db"
SNAP_FLOOR = 300
TEST_CLASSES = (2020, 2021, 2022, 2023)
FIRST_CLASS, LAST_CLASS = 2017, 2023
GROUPS = ("EDGE", "DT", "LB", "S", "CB")
PFF_TO_GROUP = {"ED": "EDGE", "DI": "DT", "LB": "LB", "CB": "CB", "S": "S"}
ALPHA, C_LOGIT, BOOT = 10.0, 0.1, 2000
B1 = ["log_pick", "age_at_draft", "height_in", "weight_lb", "speed_score", "has_forty"]
COLLEGE = ["has_college", "p5", "c_games", "snaps_pg", "tackles_pg", "tfl_pg", "sacks_pg", "stops_pg", "pbu_pg", "int_pg",
           "missed_tackle_rate", "pressure_rate", "pr_win_rate", "c_grade_defense", "c_grade_run_defense", "c_grade_coverage",
           "c_grade_pass_rush", "c_grade_tackle"]
SETS = {"B1": B1, "M": B1 + COLLEGE}


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    f = pd.read_sql("SELECT f.*, p.pff_position AS pos FROM mart_idp_prospect_features f "
                    "LEFT JOIN core_nflverse_players p ON p.gsis_id = f.gsis_id WHERE f.draft_season BETWEEN ? AND ?",
                    c, params=(FIRST_CLASS, LAST_CLASS))
    o = pd.read_sql("""SELECT gsis_id, SUM(points) points, SUM(games) games, SUM(snaps) snaps, MAX(top12) top12_any,
                       MAX(top24) top24_any, MIN(years_observed) yo FROM mart_idp_prospect_outcome GROUP BY gsis_id""", c)
    return f.merge(o, on="gsis_id", how="inner")


def prepare(d):
    n0 = len(d)
    d = d[d["yo"] == 3].copy()
    d["group"] = d["nfl_pff_position"].map(PFF_TO_GROUP)
    excluded = int(d["group"].isna().sum())
    d = d[d["group"].notna()].copy()
    d["ppg3"] = np.where((d["snaps"] >= SNAP_FLOOR) & (d["games"] > 0), d["points"] / d["games"].replace(0, np.nan), np.nan)
    d["log_pick"] = np.log(d["draft_pick"])
    d["speed_score"] = d["weight_lb"] * 200.0 / d["forty"] ** 4
    g = d["c_games"].replace(0, np.nan)
    d["snaps_pg"] = d["c_snaps_defense"] / g
    for k, c in (("tackles_pg", "c_tackles"), ("tfl_pg", "c_tfl"), ("sacks_pg", "c_sacks"), ("stops_pg", "c_stops"),
                 ("pbu_pg", "c_pass_break_ups"), ("int_pg", "c_interceptions")):
        d[k] = d[c] / g
    d["missed_tackle_rate"] = d["c_missed_tackles"] / (d["c_tackles"] + d["c_assists"] + d["c_missed_tackles"]).replace(0, np.nan)
    d["pressure_rate"] = d["c_pressures"] / d["c_snaps_pass_rush"].replace(0, np.nan)
    d["pr_win_rate"] = d["k_pr_wins"] / d["k_pr_opp"].replace(0, np.nan)
    d["p5"] = (d["conference_tier"] == "P5").astype(float)
    return d, {"joined": n0, "all_three_years": int((d.shape[0] + excluded)), "excluded_no_group": excluded}


def design(train, test, cols):
    med = train[cols].median()
    a = train[cols].fillna(med).fillna(0.0)
    b = test[cols].fillna(med).fillna(0.0)
    sc = StandardScaler().fit(a)
    return sc.transform(a), sc.transform(b), sc


def fit_predict(train, test, cols, kind):
    xa, xb, _ = design(train, test, cols)
    if kind == "reg":
        return Ridge(alpha=ALPHA).fit(xa, train["ppg3"]).predict(xb)
    m = LogisticRegression(C=C_LOGIT, max_iter=1000).fit(xa, train[kind])
    return m.predict_proba(xb)[:, 1]


def rho(a, b):
    return float(spearmanr(a, b)[0])


def boot_lift(y, p_new, p_base, rng):
    n, out = len(y), []
    for _ in range(BOOT):
        i = rng.integers(0, n, n)
        if len(set(y[i])) < 3:
            continue
        out.append(rho(p_new[i], y[i]) - rho(p_base[i], y[i]))
    return np.percentile(out, [2.5, 97.5])


def main():
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 15
    rng = np.random.default_rng(seed)
    d, info = prepare(load())
    print(f"population: joined {info['joined']}, three observed years {info['all_three_years']}, "
          f"excluded (no defender PFF position) {info['excluded_no_group']}, kept {len(d)}; snap floor {SNAP_FLOOR}; seed {seed}")
    print(d.groupby("group").agg(n=("gsis_id", "count"), with_label=("ppg3", lambda s: int(s.notna().sum())),
                                 top12=("top12_any", "sum"), top24=("top24_any", "sum")).to_string())
    verdict = {}
    for g in GROUPS:
        dg = d[d["group"] == g]
        rows = {"y": [], "b0": [], "B1": [], "M": [], "class": []}
        flag = {t: {"y": [], "B0": [], "B1": [], "M": []} for t in ("top12_any", "top24_any")}
        for n in TEST_CLASSES:
            tr, te = dg[dg["draft_season"] < n], dg[dg["draft_season"] == n]
            trl, tel = tr[tr["ppg3"].notna()], te[te["ppg3"].notna()]
            if len(trl) < 30 or len(tel) < 5:
                continue
            rows["y"] += list(tel["ppg3"]); rows["b0"] += list(-tel["draft_pick"]); rows["class"] += list(tel["draft_season"])
            for s in ("B1", "M"):
                rows[s] += list(fit_predict(trl, tel, SETS[s], "reg"))
            for t in flag:
                if tr[t].sum() < 3 or len(tr) < 30:
                    continue
                flag[t]["y"] += list(te[t])
                flag[t]["B0"] += list(fit_predict(tr, te, ["log_pick"], t))
                for s in ("B1", "M"):
                    flag[t][s] += list(fit_predict(tr, te, SETS[s], t))
        y = np.array(rows["y"])
        if len(y) < 30:
            print(f"\n{g}: only {len(y)} out-of-time players; no verdict")
            verdict[g] = "NO VERDICT"
            continue
        b0, p1, pm = np.array(rows["b0"]), np.array(rows["B1"]), np.array(rows["M"])
        r0, r1, rm = rho(b0, y), rho(p1, y), rho(pm, y)
        lo, hi = boot_lift(y, pm, b0, rng)
        lo1, hi1 = boot_lift(y, p1, b0, rng)
        lom, him = boot_lift(y, pm, p1, rng)
        print(f"\n{g}: out-of-time players {len(y)} (classes {sorted(set(rows['class']))})")
        print(f"  Spearman vs ppg3: B0 {r0:.3f}  B1 {r1:.3f}  M {rm:.3f}")
        print(f"  lift M-B0 {rm - r0:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]   B1-B0 [{lo1:+.3f}, {hi1:+.3f}]   M-B1 [{lom:+.3f}, {him:+.3f}]")
        for t, v in flag.items():
            if len(v["y"]) and len(set(v["y"])) == 2:
                yy = np.array(v["y"])
                print(f"  {t}: n {len(yy)} pos {int(yy.sum())}  AUC B0 {roc_auc_score(yy, v['B0']):.3f} B1 {roc_auc_score(yy, v['B1']):.3f} "
                      f"M {roc_auc_score(yy, v['M']):.3f}   Brier B0 {brier_score_loss(yy, v['B0']):.3f} B1 {brier_score_loss(yy, v['B1']):.3f} "
                      f"M {brier_score_loss(yy, v['M']):.3f}   base rate {yy.mean():.3f}")
        # calibration of M for top24 (quintiles of predicted probability)
        v = flag["top24_any"]
        if len(v["y"]) >= 40 and len(set(v["y"])) == 2:
            cal = pd.DataFrame({"p": v["M"], "y": v["y"]})
            cal["bin"] = pd.qcut(cal["p"], 5, duplicates="drop")
            print("  top24 calibration (M, quintiles of predicted):",
                  [(round(float(x.p.mean()), 2), round(float(x.y.mean()), 2), len(x)) for _, x in cal.groupby("bin", observed=True)])
        # coefficient signs, fit on every labelled player
        lab = dg[dg["ppg3"].notna()]
        xa, _, _ = design(lab, lab, SETS["M"])
        coef = pd.Series(Ridge(alpha=ALPHA).fit(xa, lab["ppg3"]).coef_, index=SETS["M"]).sort_values(key=abs, ascending=False)
        print("  M standardised coefficients (top 8):", ", ".join(f"{k} {v:+.2f}" for k, v in coef.head(8).items()))
        verdict[g] = "SHIP" if lo > 0 else "DO NOT SHIP"
    print("\nGATE (CI of Spearman lift over the draft-pick baseline excludes zero):")
    for g in GROUPS:
        print(f"  {g}: {verdict.get(g)}")


if __name__ == "__main__":
    main()
