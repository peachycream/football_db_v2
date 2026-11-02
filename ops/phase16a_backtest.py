"""Phase 16a backtest, exactly as PHASE16A_SPEC.md (committed 238ce9d before any number here was computed). Read-only.

Usage: python ops/phase16a_backtest.py [--seed N]
One run. Primary test per position: Spearman(PRIMARY) - Spearman(B0) against points_next (league points in season N+1, 0 when the
player has no row) on pooled out-of-time candidates (>= 300 snaps in N), player-cluster paired bootstrap, Holm over five positions;
ship only if the estimate > 0 and the adjusted p < 0.05. Everything else is descriptive. Position group "DE" is the EDGE group.
"""
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fdb.idp_prospect import LEAGUE, _closed_seasons, _finishes, _season_points  # noqa: E402
from fdb.scoring import catch_all_rules  # noqa: E402

DB = ROOT / "database" / "fdb.db"
SNAP_FLOOR = 300
FIRST_N, LAST_N = 2016, 2024
TEST_N = (2021, 2022, 2023, 2024)
GROUPS = ("DE", "DT", "LB", "S", "CB")
GRID = (3.0, 10.0, 30.0, 100.0)
BOOT = 2000

F_ALL = ["ppg_N", "log_snaps_N", "games_N", "age", "exp_yrs", "has_draft_year", "ppg_prev", "has_prev", "et_gap_pg", "has_et",
         "es_gap_pg", "has_es"]
F_S = ["ppg_N", "log_snaps_N", "games_N"]
SETS = {"PRIMARY": F_ALL,
        "P-S": F_S,
        "P-A": F_S + ["age", "exp_yrs", "has_draft_year"],
        "P-E": F_S + ["et_gap_pg", "has_et", "es_gap_pg", "has_es"]}


def panel():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rules, _ = catch_all_rules(c, LEAGUE)
    closed = [s for s in _closed_seasons(c)]
    assert max(closed) >= LAST_N + 1, closed
    rows = _season_points(c, closed, rules)
    fin = _finishes(rows)
    by = defaultdict(dict)
    dropped = 0
    for (s, key), a in rows.items():
        if not a["gsis"]:
            dropped += 1
            continue
        if s in by[a["gsis"]]:
            raise SystemExit(f"{a['gsis']}: two PFF keys in {s}")
        by[a["gsis"]][s] = (key, a)
    prof = {r["gsis_id"]: (r["birth_date"], r["draft_year"]) for r in c.execute("SELECT gsis_id, birth_date, draft_year FROM mart_player_profile")}
    et = {(r["season"], r["gsis_id"]): r["gap"] for r in c.execute(
        """SELECT season, gsis_id, SUM(actual_tackles_run + actual_tackles_pass - expected_tackles_run - expected_tackles_pass) gap
           FROM mart_idp_expected_tackles_week WHERE season_type = 'REG' GROUP BY season, gsis_id""")}
    es = {(r["season"], r["gsis_id"]): r["gap"] for r in c.execute(
        """SELECT season, gsis_id, SUM(sacks - expected_sacks) gap FROM mart_idp_expected_sacks_week
           WHERE season_type = 'REG' GROUP BY season, gsis_id""")}
    out = []
    for gsis, seasons in by.items():
        for n in range(FIRST_N, LAST_N + 1):
            hit = seasons.get(n)
            if hit is None or hit[1]["snaps"] < SNAP_FLOOR or hit[1]["group"] not in GROUPS or hit[1]["games"] <= 0:
                continue
            key, a = hit
            nxt = seasons.get(n + 1)
            prev = seasons.get(n - 1)
            bd, dy = prof.get(gsis, (None, None))
            f, tot = fin[(n + 1, nxt[1]["group"])][nxt[0]] if nxt else (None, None)
            out.append(dict(
                gsis=gsis, N=n, group=a["group"], points_N=a["points"], games_N=a["games"], snaps_N=a["snaps"],
                ppg_N=a["points"] / a["games"], log_snaps_N=np.log(a["snaps"]),
                age=(date(n + 1, 9, 1) - date.fromisoformat(bd[:10])).days / 365.25 if bd else np.nan,
                exp_yrs=(n + 1 - dy) if dy else np.nan, has_draft_year=float(bool(dy)),
                ppg_prev=prev[1]["points"] / prev[1]["games"] if prev and prev[1]["games"] > 0 else np.nan,
                et_gap_pg=et[(n, gsis)] / a["games"] if (n, gsis) in et and et[(n, gsis)] is not None else np.nan,
                es_gap_pg=es[(n, gsis)] / a["games"] if (n, gsis) in es and es[(n, gsis)] is not None else np.nan,
                points_next=nxt[1]["points"] if nxt else 0.0, snaps_next=nxt[1]["snaps"] if nxt else 0,
                games_next=nxt[1]["games"] if nxt else 0,
                top12=int(f is not None and f <= 12), top24=int(f is not None and f <= 24)))
    d = pd.DataFrame(out)
    d["has_prev"] = d["ppg_prev"].notna().astype(float)
    d["has_et"] = d["et_gap_pg"].notna().astype(float)
    d["has_es"] = d["es_gap_pg"].notna().astype(float)
    d["ppg_next"] = np.where((d["snaps_next"] >= SNAP_FLOOR) & (d["games_next"] > 0), d["points_next"] / d["games_next"].replace(0, np.nan), np.nan)
    return d, dropped


def design(train, test, cols):
    med = train[cols].median()
    a = train[cols].fillna(med).fillna(0.0)
    b = test[cols].fillna(med).fillna(0.0)
    sc = StandardScaler().fit(a)
    return sc.transform(a), sc.transform(b)


def pick_alpha(train, cols, target, logit=False):
    """Leave-one-transition-out CV inside the training transitions only."""
    ns = sorted(train["N"].unique())
    if len(ns) < 2:
        return 30.0
    best, err = GRID[2], np.inf
    for a in GRID:
        e = []
        for k in ns:
            tr, va = train[train["N"] != k], train[train["N"] == k]
            if len(va) == 0 or len(tr) < 50 or (logit and tr[target].nunique() < 2):
                continue
            xa, xb = design(tr, va, cols)
            if logit:
                p = np.clip(LogisticRegression(C=1.0 / a, max_iter=2000).fit(xa, tr[target]).predict_proba(xb)[:, 1], 1e-6, 1 - 1e-6)
                e.append(float(log_loss(va[target], p, labels=[0, 1])))
            else:
                e.append(float(np.mean((Ridge(alpha=a).fit(xa, tr[target]).predict(xb) - va[target]) ** 2)))
        if e and np.mean(e) < err:
            best, err = a, float(np.mean(e))
    return best


def fit_predict(train, test, cols, target="points_next", logit=False):
    xa, xb = design(train, test, cols)
    a = pick_alpha(train, cols, target, logit)
    if logit:
        return LogisticRegression(C=1.0 / a, max_iter=2000).fit(xa, train[target]).predict_proba(xb)[:, 1]
    return Ridge(alpha=a).fit(xa, train[target]).predict(xb)


def rho(a, b):
    return float(spearmanr(a, b)[0])


def boot_diff(y, p_new, p_base, gsis, rng):
    """Player-cluster paired bootstrap: all of a player's test rows are drawn together."""
    idx = defaultdict(list)
    for i, g in enumerate(gsis):
        idx[g].append(i)
    groups = [np.array(v) for v in idx.values()]
    out = []
    for _ in range(BOOT):
        pick = rng.integers(0, len(groups), len(groups))
        i = np.concatenate([groups[j] for j in pick])
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
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 16
    rng = np.random.default_rng(seed)
    d, dropped = panel()
    print(f"candidates {len(d)}; player-seasons without a gsis_id dropped {dropped}; seed {seed}; groups {d['group'].value_counts().to_dict()}")
    print("PRIMARY features:", F_ALL)
    pvals, diffs = {}, {}
    for g in GROUPS:
        dg = d[d["group"] == g]
        out = defaultdict(list)
        for n in TEST_N:
            tr, te = dg[dg["N"] < n], dg[dg["N"] == n]
            if len(tr) < 100 or len(te) < 10:
                continue
            for k in ("gsis", "N", "points_next", "ppg_next", "snaps_next", "top12", "top24", "age", "points_N", "ppg_N"):
                out[k] += list(te[k])
            for k, cols in SETS.items():
                out[k] += list(fit_predict(tr, te, cols))
            for t in ("top12", "top24"):
                if tr[t].sum() >= 5:
                    out[t + "_PRIMARY"] += list(fit_predict(tr, te, F_ALL, t, True))
                    out[t + "_PPG"] += list(fit_predict(tr, te, ["points_N"], t, True))
                else:
                    out[t + "_PRIMARY"] += [np.nan] * len(te)
                    out[t + "_PPG"] += [np.nan] * len(te)
        y = np.array(out["points_next"])
        gs = np.array(out["gsis"])
        P = {"B0": np.array(out["points_N"]), "B1": np.array(out["ppg_N"]), **{k: np.array(out[k]) for k in SETS}}
        res = {k: rho(P[k], y) for k in P}
        ci, p = boot_diff(y, P["PRIMARY"], P["B0"], gs, rng)
        pvals[g], diffs[g] = p, (res["PRIMARY"] - res["B0"], ci)
        print(f"\n{g}: out-of-time candidates {len(y)} ({len(set(gs))} players)")
        print("  Spearman vs points_next: " + "  ".join(f"{k} {v:.3f}" for k, v in res.items()))
        print(f"  PRIMARY-B0 {diffs[g][0]:+.3f}  95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]  p {p:.3f}")
        for k in ("P-S", "P-A", "P-E"):   # descriptive, uncorrected
            cik, pk = boot_diff(y, P[k], P["B0"], gs, rng)
            print(f"  {k} - B0 {res[k] - res['B0']:+.3f}  95% CI [{cik[0]:+.3f}, {cik[1]:+.3f}]  p {pk:.3f} (descriptive, uncorrected)")
        v = np.array(out["ppg_next"], dtype=float)
        m = ~np.isnan(v)
        print(f"  survivors, vs ppg_next (n {int(m.sum())}): B0 {rho(P['B0'][m], v[m]):.3f}  B1 {rho(P['B1'][m], v[m]):.3f}  PRIMARY {rho(P['PRIMARY'][m], v[m]):.3f}")
        for t in ("top12", "top24"):
            yy = np.array(out[t])
            sc, sp = np.array(out[t + "_PRIMARY"], dtype=float), np.array(out[t + "_PPG"], dtype=float)
            ok = ~np.isnan(sc)
            if ok.sum() and len(set(yy[ok])) == 2:
                print(f"  {t}: n {int(ok.sum())} pos {int(yy[ok].sum())}  AUC B0 {roc_auc_score(yy[ok], P['B0'][ok]):.3f} PRIMARY {roc_auc_score(yy[ok], P['PRIMARY'][ok]):.3f}"
                      f"  Brier points_N-only {brier_score_loss(yy[ok], sp[ok]):.3f} PRIMARY-logit {brier_score_loss(yy[ok], sc[ok]):.3f}")
        age = np.array(out["age"], dtype=float)
        bands = [("<25", age < 25), ("25-27", (age >= 25) & (age < 28)), ("28-30", (age >= 28) & (age < 31)), ("31+", age >= 31)]
        print("  zero points next season by age band: " + ", ".join(
            f"{b} {float((y[mk] == 0).mean()):.2f} (n {int(mk.sum())})" for b, mk in bands if mk.sum()))
        xa, _ = design(dg, dg, F_ALL)
        coef = pd.Series(Ridge(alpha=pick_alpha(dg, F_ALL, "points_next")).fit(xa, dg["points_next"]).coef_, index=F_ALL)
        print("  PRIMARY standardised coefficients:", ", ".join(f"{k} {v:+.1f}" for k, v in coef.items()))
        te_all = dg[dg["N"].isin(TEST_N)]
        print("  coverage in the test seasons (n {}): ".format(len(te_all)) + ", ".join(
            f"{k} {te_all[k].notna().mean():.2f}" for k in ("age", "exp_yrs", "ppg_prev", "et_gap_pg", "es_gap_pg")))
    adj = holm(pvals)
    print("\nGATE (primary: PRIMARY - B0 vs points_next, Holm-adjusted over five positions; ship if estimate > 0 and adjusted p < 0.05):")
    for g in GROUPS:
        est = diffs[g][0]
        print(f"  {g}: estimate {est:+.3f}, p {pvals[g]:.3f}, Holm-adjusted {adj[g]:.3f} -> {'SHIP' if est > 0 and adj[g] < 0.05 else 'DO NOT SHIP'}")


if __name__ == "__main__":
    main()
