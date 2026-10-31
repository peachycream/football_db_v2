"""Phase 15c gate: catch-all points (mart_idp_prospect_outcome's scale) vs MFL's REPORTED points, 2025, by position group.

Usage: python ops/phase15c_reconcile.py [league_id] [season]   (read-only)
Players are joined by exact ids (mart_mfl_reported_week.pff_id = the PFF player_key); no name is read.
Gate (PHASE15_PROMPT 15c): Spearman rank correlation >= 0.95 per position. Reported and predicted are season totals over the
regular season; players with fewer than MIN_REPORTED reported points are left out (nothing to rank).
"""
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fdb import idp_prospect  # noqa: E402
from fdb.scoring import catch_all_rules  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "database" / "fdb.db"
LEAGUE = sys.argv[1] if len(sys.argv) > 1 else idp_prospect.LEAGUE
SEASON = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
MIN_REPORTED = 20.0
GATE = 0.95


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return cov / (va * vb) ** 0.5


c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
rules, rule_season = catch_all_rules(c, LEAGUE)
pred = idp_prospect._season_points(c, [SEASON], rules)
rep = defaultdict(float)
for r in c.execute("""SELECT pff_id, SUM(score) s FROM mart_mfl_reported_week WHERE league_id = ? AND season = ?
                      AND season_type = 'REG' AND pff_id IS NOT NULL GROUP BY pff_id""", (LEAGUE, SEASON)):
    rep["pff:" + r["pff_id"]] = r["s"] or 0.0
print(f"league {LEAGUE} season {SEASON} (rules of {rule_season}); reported ids {len(rep)}, predicted defenders {len(pred)}")
by = defaultdict(lambda: ([], []))
for (s, key), a in pred.items():
    if key in rep and rep[key] >= MIN_REPORTED:
        by[a["group"]][0].append(rep[key])
        by[a["group"]][1].append(a["points"])
ok = True
for g in idp_prospect.GROUPS:
    r, p = by[g]
    if len(r) < 10:
        print(f"  {g}: only {len(r)} players")
        ok = False
        continue
    rho = spearman(r, p)
    ratio = sorted(x / y for x, y in zip(r, p) if y > 0)[len(r) // 2]
    print(f"  {g}: n={len(r)} spearman={rho:.4f} median reported/predicted={ratio:.3f} {'OK' if rho >= GATE else 'BELOW ' + str(GATE)}")
    ok = ok and rho >= GATE
print("GATE MET" if ok else "GATE NOT MET")
