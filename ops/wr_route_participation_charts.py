"""WR route participation charts (read-only against the v1 football.db).

Spec: wr_route_participation_charts.md. Sums totals across weeks, then computes rates.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from adjustText import adjust_text

DB = r"C:\Users\k-ble\Desktop\football_db\database\football.db"
SPOT = ["Zay Flowers", "Jaxon Smith-Njigba", "Justin Jefferson", "CeeDee Lamb", "Mack Hollins", "Puka Nacua"]
SRC_TXT = ["Data: FantasyPointsData via football.db"]


def probe(con, table):
    print(f"\n[probe] PRAGMA table_info({table})")
    cols = [(r[1], r[2]) for r in con.execute(f"PRAGMA table_info({table})")]
    print("  " + ", ".join(f"{n}:{t}" for n, t in cols))
    return {n for n, _ in cols}


def parse_weeks(s):
    a, _, b = s.partition("-")
    return int(a), (int(b) if b else int(a))


def regress(x, y):
    m, b = np.polyfit(x, y, 1)
    r2 = np.corrcoef(x, y)[0, 1] ** 2
    return m, b, r2


def label(ax, df, xcol, ycol, fs=7):
    texts = [ax.text(r[xcol], r[ycol], r["name"], fontsize=fs) for _, r in df.iterrows()]
    adjust_text(texts, ax=ax, arrowprops=dict(arrowstyle="-", color="gray", lw=0.4))


def frame(ax, title, sub, xl, yl):
    ax.set_title(title + "\n", fontsize=14, fontweight="bold", loc="left")
    ax.text(0, 1.01, sub, transform=ax.transAxes, fontsize=9, color="dimgray")
    ax.set_xlabel(xl)
    ax.set_ylabel(yl)
    ax.figure.text(0.01, 0.01, SRC_TXT[0], fontsize=7, color="gray")
    ax.grid(alpha=0.2)


def medians(ax, x, y):
    ax.axvline(np.median(x), ls="--", color="gray", lw=0.8)
    ax.axhline(np.median(y), ls="--", color="gray", lw=0.8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--weeks", default=None, help="e.g. 1-5; default 1..latest loaded")
    ap.add_argument("--position", default="WR")
    ap.add_argument("--min-routes", type=int, default=50)
    ap.add_argument("--min-rp", type=float, default=0.0)
    ap.add_argument("--chart-c-min-rp", type=float, default=0.60)
    ap.add_argument("--drop-partial", dest="drop_partial", action="store_true", default=True)
    ap.add_argument("--keep-partial", dest="drop_partial", action="store_false")
    ap.add_argument("--out", default=None)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--source", choices=["fpd", "ftn"], default="fpd",
                    help="fpd: FPD routes+XFP+FP. ftn: routes from FTN participation, XFP/FP from ff_opportunity")
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{Path(a.db).as_posix()}?mode=ro", uri=True)

    # ---- Phase 0
    print("=== PHASE 0: schema and coverage probe ===")
    adv = probe(con, "fpd_receiving_advanced_weekly")
    need = {"player_id", "season", "week", "team", "routes_run", "expected_fpts", "fpts", "position_fpd"}
    assert need <= adv, f"missing columns: {need - adv}"
    probe(con, "players")
    probe(con, "team_env_weekly")
    rr = probe(con, "fpd_receiving_routes_run_weekly")
    print("\n[note] fpd_receiving_routes_run_weekly exists (personnel grain; routes_total). Not used: "
          "advanced_weekly.routes_run is already one row per player-week.")
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY 1")]
    cand = [n for n in names if any(k in n.lower() for k in ("team", "pbp", "dropback", "pass"))]
    print("\n[probe] team-level candidates:", cand)
    n_env = con.execute("SELECT COUNT(*) FROM team_env_weekly WHERE season=? AND side='off' AND split='all' AND dropbacks IS NOT NULL",
                        (a.season,)).fetchone()[0]
    print(f"[probe] team dropback source: team_env_weekly (side='off', split='all', dropbacks) rows for {a.season}: {n_env}")
    seasons = con.execute("SELECT season, MAX(week), COUNT(*) FROM fpd_receiving_advanced_weekly "
                          "GROUP BY season ORDER BY 1 DESC LIMIT 3").fetchall()
    print("[probe] fpd_receiving_advanced_weekly (season, max week, rows):", seasons)
    if n_env == 0:
        sys.exit("STOP: no team-dropback source for this season. Fallback proposal: nflverse pbp, "
                 "sum qb_dropback==1 by posteam, season, week. Nothing downloaded.")
    if a.source == "ftn":
        probe(con, "ftn_participation_players")
        probe(con, "ftn_player_xwalk")
        probe(con, "ff_opportunity")
        print("[probe] ftn roles:", con.execute("SELECT role, COUNT(*) FROM ftn_participation_players WHERE season=? "
                                              "GROUP BY role", (a.season,)).fetchall())
        SRC_TXT[0] = "Data: FTN participation on PASS plays (routes) + ff_opportunity (XFP/FP) via football.db"
        mx = con.execute("SELECT MAX(week) FROM ftn_participation_players WHERE season=?", (a.season,)).fetchone()[0]
    else:
        mx = con.execute("SELECT MAX(week) FROM fpd_receiving_advanced_weekly WHERE season=?", (a.season,)).fetchone()[0]
    if mx is None:
        sys.exit(f"STOP: fpd_receiving_advanced_weekly has no rows for season {a.season} "
                 f"(latest loaded season: {seasons[0][0]}). Nothing to chart.")
    w0, w1 = parse_weeks(a.weeks) if a.weeks else (1, mx)
    w1 = min(w1, mx)
    print(f"[probe] max week loaded {a.season}: {mx}; using weeks {w0}-{w1}")
    print("[probe] WR players per week:",
          con.execute("SELECT t.week, COUNT(*) FROM fpd_receiving_advanced_weekly t JOIN players p "
                      "ON p.player_id=t.player_id WHERE t.season=? AND p.position=? GROUP BY t.week",
                      (a.season, a.position)).fetchall())
    print("[probe] position source: players.position (trusted); fpd position_fpd shown only for comparison")

    # ---- Phase 1
    print("\n=== PHASE 1: player-week table ===")
    if a.source == "ftn":
        sql = """WITH r AS (
                   SELECT x.player_id, pp.season, pp.week, COUNT(*) AS routes_run
                   FROM ftn_participation_players pp
                   JOIN ftn_player_xwalk x ON x.ftn_player_id = pp.ftn_player_id
                   JOIN ftn_charts fc ON fc.gid = pp.gid AND fc.pid = pp.pid AND fc.type = 'PASS'
                   WHERE pp.role IN ('RTE','FRTE','BRTE') AND pp.season=? GROUP BY 1,2,3)
                 SELECT t.player_id, p.full_name AS name, t.team, t.week, r.routes_run,
                        t.rec_fantasy_points_exp AS xfp, t.rec_fantasy_points AS fp, e.dropbacks AS team_dropbacks
                 FROM ff_opportunity t
                 JOIN players p ON p.player_id = t.player_id
                 LEFT JOIN r ON r.player_id=t.player_id AND r.season=t.season AND r.week=t.week
                 LEFT JOIN team_env_weekly e ON e.season=t.season AND e.week=t.week AND e.team=t.team
                      AND e.side='off' AND e.split='all'
                 WHERE t.season=? AND t.week BETWEEN ? AND ? AND p.position=?"""
        prm = (a.season, a.season, w0, w1, a.position)
    else:
        sql = None
    df = pd.read_sql_query(
        sql, con, params=prm) if sql else pd.read_sql_query(
        """SELECT t.player_id, p.full_name AS name, t.team, t.week, t.routes_run,
                  t.expected_fpts AS xfp, t.fpts AS fp, e.dropbacks AS team_dropbacks
           FROM fpd_receiving_advanced_weekly t
           JOIN players p ON p.player_id = t.player_id
           LEFT JOIN team_env_weekly e ON e.season=t.season AND e.week=t.week AND e.team=t.team AND e.side='off' AND e.split='all'
           WHERE t.season=? AND t.week BETWEEN ? AND ? AND p.position=?""",
        con, params=(a.season, w0, w1, a.position))
    print("rows (position-filtered player-weeks):", len(df))
    nodb = df[df.team_dropbacks.isna() | (df.team_dropbacks <= 0)]
    print("rows without team dropbacks:", len(nodb))
    if len(nodb):
        print(nodb.groupby("team").size().to_string())
    df = df.drop(nodb.index)
    z = df[(df.routes_run.isna()) | (df.routes_run == 0)]
    print("rows with routes_run == 0/null (excluded):", len(z))
    df = df.drop(z.index)
    df["rp"] = df.routes_run / df.team_dropbacks
    df["partial"] = df.rp < 0.35
    print("rows partial (RP<0.35):", int(df.partial.sum()))
    if a.drop_partial:
        d = df[df.partial]
        print("dropped partial player-weeks:")
        print(d[["name", "team", "week", "routes_run", "team_dropbacks", "rp"]].round(3).to_string(index=False)
              if len(d) < 200 else f"  ({len(d)} rows; too many to list)")
        df = df[~df.partial]
    print("rows after phase 1:", len(df))

    # ---- Phase 2
    print("\n=== PHASE 2: season-to-date metrics ===")
    g = df.groupby(["player_id", "name"], as_index=False).agg(
        team=("team", "last"), routes=("routes_run", "sum"), dropbacks=("team_dropbacks", "sum"),
        xfp=("xfp", "sum"), fp=("fp", "sum"), weeks_included=("week", "nunique"))
    g["RP"] = g.routes / g.dropbacks
    g["XFP_RR"] = g.xfp / g.routes
    g["FP_RR"] = g.fp / g.routes
    g["XFP_DB"] = g.xfp / g.dropbacks
    g["FP_DB"] = g.fp / g.dropbacks
    g["delta_RR"] = g.FP_RR - g.XFP_RR
    g["delta_DB"] = g.FP_DB - g.XFP_DB
    print("players before filters:", len(g))
    g = g[g.routes >= a.min_routes]
    print(f"after min-routes {a.min_routes}:", len(g))
    g = g[g.RP >= a.min_rp]
    print(f"after min-rp {a.min_rp}:", len(g))
    g = g.sort_values("XFP_DB", ascending=False).reset_index(drop=True)
    if g.empty:
        sys.exit("No players left after filters.")

    out = Path(a.out) if a.out else Path("output/route_participation") / f"{a.season}_wk{w0}-{w1}"
    out.mkdir(parents=True, exist_ok=True)
    csv = out / f"wr_route_participation_{a.season}_wk{w0}-{w1}.csv"
    g.to_csv(csv, index=False)
    pd.set_option("display.width", 250)
    print(g[["name", "team", "weeks_included", "routes", "dropbacks", "RP", "XFP_RR", "FP_RR",
             "XFP_DB", "FP_DB", "delta_RR", "delta_DB"]].round(3).to_string(index=False))

    sub = (f"{a.season} wk {w0}-{w1} | {a.position} | min {a.min_routes} routes, RP>={a.min_rp:.2f} | "
           f"partial weeks (RP<35%) {'dropped' if a.drop_partial else 'kept'} | n={len(g)}")
    paths = []

    # ---- Chart A
    fig, ax = plt.subplots(figsize=(12, 8.5))
    sc = ax.scatter(g.RP, g.XFP_RR, c=g.XFP_DB, cmap="viridis", s=45, edgecolor="k", lw=0.3, zorder=3)
    fig.colorbar(sc, ax=ax, label="XFP per team dropback")
    xs = np.linspace(max(g.RP.min() * 0.9, 0.02), min(1.0, g.RP.max() * 1.1 + 0.02), 200)
    lv = np.round(np.quantile(g.XFP_DB, [0.1, 0.3, 0.5, 0.7, 0.9]), 2)
    ymax = g.XFP_RR.max() * 1.1
    for v in sorted(set(lv)):
        ys = v / xs
        m = ys <= ymax
        ax.plot(xs[m], ys[m], color="gray", lw=0.7, ls=":", zorder=1)
        if m.any():
            ax.text(xs[m][-1], ys[m][-1], f" {v:.2f}", fontsize=7, color="gray", va="center")
    medians(ax, g.RP, g.XFP_RR)
    mx_, my_ = g.RP.median(), g.XFP_RR.median()
    k = dict(fontsize=11, color="gray", alpha=0.45, style="italic")
    ax.text(0.98, 0.97, "Alpha role", transform=ax.transAxes, ha="right", va="top", **k)
    ax.text(0.02, 0.97, "Part-time, earns looks", transform=ax.transAxes, va="top", **k)
    ax.text(0.98, 0.03, "Full-time, not featured", transform=ax.transAxes, ha="right", **k)
    ax.text(0.02, 0.03, "Fringe", transform=ax.transAxes, **k)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(top=ymax)
    frame(ax, "WR Role Map: Route Participation vs XFP per Route", sub + " | dotted = XFP per dropback",
          "Route participation (routes / team dropbacks)", "XFP per route run")
    label(ax, g, "RP", "XFP_RR")
    p = out / "chart_A_role_map.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # ---- Chart B
    fig, ax = plt.subplots(figsize=(12, 8.5))
    m, b, r2 = regress(g.XFP_DB, g.FP_DB)
    lim = max(abs(g.delta_DB).max(), 1e-9)
    sc = ax.scatter(g.XFP_DB, g.FP_DB, c=g.delta_DB, cmap="RdBu", vmin=-lim, vmax=lim, s=45,
                    edgecolor="k", lw=0.3, zorder=3)
    fig.colorbar(sc, ax=ax, label="FP/DB - XFP/DB (red = under, blue = over)")
    xl = np.array([g.XFP_DB.min(), g.XFP_DB.max()])
    ax.plot(xl, m * xl + b, ls="--", color="gray", label=f"OLS: y={m:.2f}x{b:+.3f}, R²={r2:.2f}")
    medians(ax, g.XFP_DB, g.FP_DB)
    ax.legend(loc="upper left")
    frame(ax, "WR Volume-Adjusted: XFP vs FP per Team Dropback", sub,
          "XFP per team dropback", "FP per team dropback")
    label(ax, g, "XFP_DB", "FP_DB")
    p = out / "chart_B_volume_adjusted.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # ---- Chart C
    c = g[g.RP >= a.chart_c_min_rp]
    print(f"\nChart C: RP >= {a.chart_c_min_rp:.2f} -> {len(c)} players")
    fig, ax = plt.subplots(figsize=(12, 8.5))
    if len(c) >= 3:
        s = 20 + 380 * ((c.RP - c.RP.min()) / max(c.RP.max() - c.RP.min(), 1e-9))
        ax.scatter(c.XFP_RR, c.FP_RR, s=s, c="tab:blue", alpha=0.6, edgecolor="k", lw=0.4, zorder=3)
        m, b, r2 = regress(c.XFP_RR, c.FP_RR)
        xl = np.array([c.XFP_RR.min(), c.XFP_RR.max()])
        ax.plot(xl, m * xl + b, ls="--", color="gray", label=f"OLS: y={m:.2f}x{b:+.3f}, R²={r2:.2f}")
        medians(ax, c.XFP_RR, c.FP_RR)
        for rp in (c.RP.min(), c.RP.median(), c.RP.max()):
            sz = 20 + 380 * ((rp - c.RP.min()) / max(c.RP.max() - c.RP.min(), 1e-9))
            ax.scatter([], [], s=sz, c="tab:blue", alpha=0.6, edgecolor="k", label=f"RP {rp:.0%}")
        ax.legend(loc="upper left", title="Dot size = RP")
        label(ax, c, "XFP_RR", "FP_RR")
    frame(ax, "WR XFP vs FP per Route, RP-Weighted",
          sub.replace(f"RP>={a.min_rp:.2f}", f"RP>={a.chart_c_min_rp:.2f}"), "XFP per route run", "FP per route run")
    p = out / "chart_C_rp_weighted.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # ---- Phase 4
    print("\n=== PHASE 4: validation ===")
    print("RP > 1.00:", g[g.RP > 1.0][["name", "RP"]].round(3).values.tolist() or "none")
    print("RP > 1.05 (fail):", "YES" if (g.RP > 1.05).any() else "none")
    print("null XFP:", int(g.xfp.isna().sum()))
    print("players: total", len(g), "| RP<0.60:", int((g.RP < 0.60).sum()), "| chart C:", len(c))
    print("\nSpot checks:")
    for n in SPOT:
        r = g[g.name == n]
        print(f"  {n}: RP={r.RP.iloc[0]:.3f} XFP_DB={r.XFP_DB.iloc[0]:.3f}" if len(r)
              else f"  {n}: not in filtered set")
    cols = ["name", "team", "RP", "XFP_DB", "FP_DB", "delta_DB"]
    print("\nTop 10 delta_DB (sell-high):\n", g.nlargest(10, "delta_DB")[cols].round(3).to_string(index=False))
    print("\nBottom 10 delta_DB (buy-low):\n", g.nsmallest(10, "delta_DB")[cols].round(3).to_string(index=False))
    rg = g[g.RP < 0.60].nlargest(10, "XFP_RR")
    print("\nRole-growth watch (RP<0.60, top 10 XFP_RR):\n",
          rg[["name", "team", "RP", "XFP_RR", "XFP_DB"]].round(3).to_string(index=False))

    print("\nOutputs:")
    for p in paths + [csv]:
        print("  ", p.resolve())
    print("\nNotes: tables = fpd_receiving_advanced_weekly (routes_run, expected_fpts=XFP, fpts=FP, team), "
          "players (full_name, position), team_env_weekly (side='off', split='all', dropbacks). "
          "Team dropbacks = team_env_weekly.dropbacks matched on season+week+team abbreviation.")


if __name__ == "__main__":
    main()
