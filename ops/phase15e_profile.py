"""Phase 15e follow-up (Turon's request): work backwards from pro success. Which college stats did the players who reached the
top 12 / top 24 at their position (any of NFL years 1-3) have in common, by position? Descriptive, read-only; stores nothing.

Usage: python ops/phase15e_profile.py [--seed N]
Population as phase15e_backtest.py: draft classes 2017-2023 (three observed NFL years), position from players.pff_position.
Flags: top12_any / top24_any from mart_idp_prospect_outcome (every player has one; no snap floor).
For each position, flag and stat:
  RAW       median of the stat for successful players vs the rest, and the univariate AUC (0.5 = no information; > 0.5 means more of
            the stat goes with success).
  ADJUSTED  partial Spearman correlation of the stat with the flag AFTER removing the draft slot (log pick) from both: does the
            stat say anything the draft slot does not? Permutation p-value (5,000 shuffles), then Benjamini-Hochberg across the
            stats of that position and flag. Roughly 30 stats x 5 positions x 2 flags are looked at, so q (not p) is what counts.
This is exploration, not a model and not a gate: a stat that survives is a lead for a NEW pre-registered test.
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score

DB = Path(__file__).resolve().parent.parent / "database" / "fdb.db"
PERM = 5000
GROUPS = ("EDGE", "DT", "LB", "S", "CB")
PFF_TO_GROUP = {"ED": "EDGE", "DI": "DT", "LB": "LB", "CB": "CB", "S": "S"}
STATS = ["age_at_draft", "height_in", "weight_lb", "speed_score", "p5", "c_games", "snaps_pg", "tackles_pg", "tfl_pg", "sacks_pg",
         "stops_pg", "pbu_pg", "int_pg", "missed_tackle_rate", "pressure_rate", "hurry_rate", "pr_win_rate", "box_share",
         "slot_share", "dl_share", "offball_share", "corner_share", "fs_share", "cov_yards_per_target", "catch_rate_allowed",
         "c_grade_defense", "c_grade_run_defense", "c_grade_coverage", "c_grade_pass_rush", "c_grade_tackle"]


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    f = pd.read_sql("SELECT f.*, o.top12_any, o.top24_any, o.yo FROM mart_idp_prospect_features f JOIN "
                    "(SELECT gsis_id, MAX(top12) top12_any, MAX(top24) top24_any, MIN(years_observed) yo "
                    " FROM mart_idp_prospect_outcome GROUP BY gsis_id) o ON o.gsis_id = f.gsis_id "
                    "WHERE f.draft_season BETWEEN 2017 AND 2023", c)
    f = f[f["yo"] == 3].copy()
    f["group"] = f["nfl_pff_position"].map(PFF_TO_GROUP)
    f = f[f["group"].notna()].copy()
    g = f["c_games"].replace(0, np.nan)
    sn = f["c_snaps_defense"].replace(0, np.nan)
    f["log_pick"] = np.log(f["draft_pick"])
    f["speed_score"] = f["weight_lb"] * 200.0 / f["forty"] ** 4
    f["p5"] = (f["conference_tier"] == "P5").astype(float)
    f["snaps_pg"] = f["c_snaps_defense"] / g
    for k, c_ in (("tackles_pg", "c_tackles"), ("tfl_pg", "c_tfl"), ("sacks_pg", "c_sacks"), ("stops_pg", "c_stops"),
                  ("pbu_pg", "c_pass_break_ups"), ("int_pg", "c_interceptions")):
        f[k] = f[c_] / g
    f["missed_tackle_rate"] = f["c_missed_tackles"] / (f["c_tackles"] + f["c_assists"] + f["c_missed_tackles"]).replace(0, np.nan)
    prs = f["c_snaps_pass_rush"].replace(0, np.nan)
    f["pressure_rate"] = f["c_pressures"] / prs
    f["hurry_rate"] = f["c_hurries"] / prs
    f["pr_win_rate"] = f["k_pr_wins"] / f["k_pr_opp"].replace(0, np.nan)
    for k, c_ in (("box", "c_snaps_box"), ("slot", "c_snaps_slot"), ("dl", "c_snaps_dl"), ("offball", "c_snaps_offball"),
                  ("corner", "c_snaps_corner"), ("fs", "c_snaps_fs")):
        f[f"{k}_share"] = f[c_] / sn
    f["cov_yards_per_target"] = f["c_cov_yards"] / f["c_targets"].replace(0, np.nan)
    f["catch_rate_allowed"] = f["c_receptions"] / f["c_targets"].replace(0, np.nan)
    return f


def resid(x, z):
    """Residual of x on [1, z] (least squares)."""
    a = np.column_stack([np.ones(len(z)), z])
    return x - a @ np.linalg.lstsq(a, x, rcond=None)[0]


def partial_perm(stat, flag, pick, rng):
    rs, rf, rp = rankdata(stat), rankdata(flag), rankdata(pick)
    a, b = resid(rs, rp), resid(rf, rp)
    if a.std() == 0 or b.std() == 0:
        return 0.0, 1.0
    r = float(np.corrcoef(a, b)[0, 1])
    null = np.array([np.corrcoef(rng.permutation(a), b)[0, 1] for _ in range(PERM)])
    return r, float((np.abs(null) >= abs(r)).mean())


def bh(p):
    p = np.asarray(p)
    order = np.argsort(p)
    q = np.empty(len(p))
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, p[i] * len(p) / rank)
        q[i] = prev
    return q


def main():
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 15
    rng = np.random.default_rng(seed)
    f = load()
    print(f"players {len(f)}; seed {seed}")
    for g in GROUPS:
        dg = f[f["group"] == g]
        for t in ("top12_any", "top24_any"):
            rows = []
            for s in STATS:
                d = dg[dg[s].notna() & dg["log_pick"].notna()]
                if d[t].sum() < 5 or (len(d) - d[t].sum()) < 5 or d[s].nunique() < 3:
                    continue
                y = d[t].to_numpy()
                auc = roc_auc_score(y, d[s])
                r, p = partial_perm(d[s].to_numpy(), y.astype(float), d["log_pick"].to_numpy(), rng)
                rows.append(dict(stat=s, n=len(d), med_success=d.loc[d[t] == 1, s].median(), med_rest=d.loc[d[t] == 0, s].median(),
                                 auc=auc, partial_r=r, p=p))
            res = pd.DataFrame(rows)
            res["q"] = bh(res["p"])
            npos = int(dg[t].sum())
            print(f"\n=== {g} {t}: {npos} successful of {len(dg)} (stats tested {len(res)}) ===")
            keep = res.reindex(res["partial_r"].abs().sort_values(ascending=False).index).head(8)
            print(keep.round(3).to_string(index=False))
            print(f"  survive q < 0.10 after the draft slot: {list(res.loc[res['q'] < 0.10, 'stat'])}; "
                  f"raw AUC >= 0.65 or <= 0.35: {list(res.loc[(res['auc'] >= 0.65) | (res['auc'] <= 0.35), 'stat'])}")


if __name__ == "__main__":
    main()
