"""IDP start/sit analysis (read-only; REBUILD_LOG "IDP start/sit"). Everything is computed at READ time from
`mart_idp_week`, `mart_idp_league_player` and the league's MFL rules (rule 4: counts stored, no rate stored, no
rate averaged: every per-snap rate is SUM(points) / SUM(snaps)).

What it answers, per MFL league (never pooled across leagues: scoring differs):
  1. How each IDP's points are made, by category, under THAT league's MFL rules (additive per position, as
     fdb/scoring.py measured), reconciled to MFL's own reported player-week score.
  2. Which categories are stable. Categories sit in three tiers declared BEFORE looking at the data:
       stable   = solo tackles, assisted tackles
       semi     = tackles for loss, QB hits, passes defended
       volatile = sacks, forced fumbles, interceptions, fumble recoveries, return TDs / safeties
     The measured split-half reliability (odd vs even games, Spearman-Brown, position-demeaned) is reported next to
     the declaration, so a category that does not behave like its tier shows up as such.
  3. Snap-share trend: last 3 games vs the 3 before, +-5 points of defensive snap share.
  4. A start score = expected snaps (recency-weighted snap share x team snaps) x per-snap production per tier,
     each tier shrunk toward the position mean with weight g/(g+k), k from the tier's measured reliability.
  5. A walk-forward check on 2026 (reliability taken from 2025 only): the score against season-to-date PPG and
     last-3 PPG, for each week.
"""
import math

import numpy as np
import pandas as pd

from .scoring import MFL_POSITIONS, Rule

POSITIONS = ("DT", "DE", "LB", "CB", "S")
SEASON = 2026
MIN_AVG_SNAP, MIN_GAMES = 0.25, 3            # the page's default pool (a toggle shows everyone)
RELIABILITY_MIN_GAMES = 6                    # a player-season needs this many games to enter a split-half
TREND_POINTS = 0.05                          # +-5 points of snap share
RECENCY = (0.4, 0.3, 0.2, 0.1)               # newest game first, for expected snap share

# stat column -> MFL event codes, first one a league's rules name for the position wins.
# TKD / ASD are 46276's names for solo / assisted tackles (TK / AS in the other leagues). scoring.py's STAT_EVENTS
# does not know them, so IDP tackles in 46276 are unscored there; this module carries its own table and leaves
# scoring.py untouched.
EVENTS = {
    "tackles": ["TK", "TKD"], "assists": ["AS", "ASD"], "tfl": ["TKL"], "sacks": ["SK"], "qb_hits": ["QH"],
    "pass_breakups": ["PD"], "interceptions": ["IC"], "forced_fumbles": ["FF"], "fumble_recoveries": ["FC", "FR"],
    "int_tds": ["#IR"], "fr_tds": ["#DR"], "safeties": ["SF"],
}
# key, label, declared tier, stat columns
CATS = [
    ("tackles", "Solo tackles", "stable", ["tackles"]),
    ("assists", "Assisted tackles", "stable", ["assists"]),
    ("tfl", "Tackles for loss", "semi", ["tfl"]),
    ("qb_hits", "QB hits", "semi", ["qb_hits"]),
    ("pass_breakups", "Passes defended", "semi", ["pass_breakups"]),
    ("sacks", "Sacks", "volatile", ["sacks"]),
    ("forced_fumbles", "Forced fumbles", "volatile", ["forced_fumbles"]),
    ("interceptions", "Interceptions", "volatile", ["interceptions"]),
    ("fumble_recoveries", "Fumble recoveries", "volatile", ["fumble_recoveries"]),
    ("scores", "Return TDs / safeties", "volatile", ["int_tds", "fr_tds", "safeties"]),
]
TIERS = ("stable", "semi", "volatile")
CAT_KEYS = [c[0] for c in CATS]
STAT_COLS = [col for c in CATS for col in c[3]]


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)


def _clean(x):
    """JSON-safe: numpy -> python, NaN/inf -> None."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


# ---------------------------------------------------------------------------------------------- scoring
def league_rules(conn, league_id):
    """({pos: {event: [Rule]}}, rule season). The catch-all row (names every position) always applies; of the other rows
    naming a position for an event, only the NARROWEST group applies. Measured in 60856: CB has a CB-only tackle row
    and a shared S|CB row, and MFL applies the CB-only one (CB exact 14% -> 91% when the S|CB row is dropped); S has no
    S-only row and takes S|CB (93% exact). fdb/scoring.py adds every row (additive); that is unchanged, and differs
    from this only where a league has overlapping multi-position groups."""
    rows = conn.execute('SELECT season, positions, event, "range", points FROM mart_mfl_rules WHERE league_id = ?',
                        (league_id,)).fetchall()
    if not rows:
        return {}, None
    full = len(MFL_POSITIONS)
    out = {}
    for pos in MFL_POSITIONS:
        by_ev = {}
        for r in rows:
            grp = set(r["positions"].split("|"))
            if pos in grp:
                by_ev.setdefault(r["event"], []).append((len(grp), r))
        out[pos] = {}
        for ev, lst in by_ev.items():
            narrow = min((n for n, _ in lst if n < full), default=None)
            out[pos][ev] = [Rule(r["range"], r["points"]) for n, r in lst if n >= full or n == narrow]
    return out, rows[0]["season"]


def _event_rules(rules, pos, col):
    rl = rules.get(pos, {})
    for e in EVENTS[col]:
        if e in rl:
            return rl[e]
    return []


def load_frame(conn, league_id):
    """Player-game frame for one league: one row per defender-game of a player MFL lists at an IDP position in
    this league, with per-category points under the league's rules. Returns (df, info)."""
    rules, rule_season = league_rules(conn, league_id)
    if not rules:
        raise ValueError(f"no MFL rules for league {league_id}")
    lp = _q(conn, "SELECT gsis_id, mfl_id, name, mfl_position FROM mart_idp_league_player WHERE league_id = ? "
                  "AND season = (SELECT MAX(season) FROM core_mfl_players WHERE league_id = ?)", (league_id, league_id))
    dup = lp[lp.duplicated("gsis_id", keep=False)]
    lp = lp.drop_duplicates("gsis_id", keep=False)           # one gsis -> two MFL ids is ambiguous: excluded, counted
    wk = _q(conn, "SELECT * FROM mart_idp_week")
    # a week with (almost) no nflverse defender rows is a data lag, not a week of zeros
    stat_rows = wk.groupby(["season", "week"])["has_stat_row"].sum()
    lagging = [(int(s), int(w)) for (s, w), n in stat_rows.items() if n < 100]
    if lagging:
        wk = wk[~wk.set_index(["season", "week"]).index.isin(lagging)]
    n_snap_players = wk[wk.season == SEASON]["gsis_id"].nunique()
    df = wk.merge(lp, on="gsis_id", how="inner")
    df[STAT_COLS] = df[STAT_COLS].fillna(0.0)
    for c in STAT_COLS:
        df["p_" + c] = 0.0
    cache = {}
    for pos in POSITIONS:
        m = df["mfl_position"] == pos
        for c in STAT_COLS:
            rl = _event_rules(rules, pos, c)
            if not rl:
                continue
            def pts(v, rl=rl, key=(pos, c)):
                k = (key, v)
                if k not in cache:
                    cache[k] = sum(r.points(v) for r in rl)
                return cache[k]
            df.loc[m, "p_" + c] = df.loc[m, c].map(pts)
    for key, _label, _tier, cols in CATS:
        df["pts_" + key] = df[["p_" + c for c in cols]].sum(axis=1)
    for t in TIERS:
        df["tier_" + t] = df[["pts_" + c[0] for c in CATS if c[2] == t]].sum(axis=1)
    df["total"] = df[["tier_" + t for t in TIERS]].sum(axis=1)
    df = df.rename(columns={"mfl_position": "pos"})
    info = {"rule_season": rule_season, "lagging_weeks": lagging, "ambiguous_gsis": int(dup["gsis_id"].nunique()),
            "snap_players": int(n_snap_players), "mapped_players": int(df[df.season == SEASON]["gsis_id"].nunique()),
            "scored_cols": sorted({c for pos in POSITIONS for c in STAT_COLS if _event_rules(rules, pos, c)}),
            "unscored_cols": sorted({c for c in STAT_COLS if not any(_event_rules(rules, p, c) for p in POSITIONS)})}
    return df, info


def reconcile(conn, league_id, df):
    """Our per-game total against MFL's own reported player-week score (exact mfl id)."""
    rep = _q(conn, "SELECT season, week, mfl_id, score FROM mart_mfl_reported_week WHERE league_id = ? AND season_type = 'REG'",
             (league_id,))
    m = df.merge(rep, on=["season", "week", "mfl_id"], how="inner")
    if m.empty:
        return {"n": 0}
    d = m["total"] - m["score"]
    out = {"n": int(len(m)), "exact": float((d.abs() < 0.01).mean()), "within_1": float((d.abs() <= 1.0).mean()),
           "mean_abs": float(d.abs().mean()), "median_abs": float(d.abs().median())}
    sea = m[m.season == SEASON].groupby("gsis_id")[["total", "score"]].sum()
    out["season_spearman"] = float(sea["total"].corr(sea["score"], method="spearman")) if len(sea) > 5 else None
    out["season_ratio"] = float(sea["total"].sum() / sea["score"].sum()) if sea["score"].sum() else None
    out["by_pos"] = {p: float((d[m.pos == p].abs() < 0.01).mean()) for p in POSITIONS if (m.pos == p).any()}
    return out


# ------------------------------------------------------------------------------------ stability analysis
def _player_seasons(df):
    """One row per (season, gsis): games, snaps, mean snap share, points by category / tier."""
    agg = {"games": ("week", "count"), "snaps": ("defense_snaps", "sum"), "avg_pct": ("defense_pct", "mean"),
           "total": ("total", "sum")}
    for k in CAT_KEYS:
        agg["pts_" + k] = ("pts_" + k, "sum")
    for t in TIERS:
        agg["tier_" + t] = ("tier_" + t, "sum")
    g = df.groupby(["season", "gsis_id", "pos"]).agg(**agg).reset_index()
    return g


def qualified(ps):
    return ps[(ps.games >= RELIABILITY_MIN_GAMES) & (ps.avg_pct >= MIN_AVG_SNAP)]


def split_half(df, seasons):
    """Odd/even-game split-half reliability, per category and tier, by position-demeaned per-snap rate.
    Returns {name: {"r_half", "r_full", "n"}, ...} with "all" and per-position blocks, plus the mean games used."""
    d = df[df.season.isin(seasons)].sort_values(["season", "gsis_id", "week"]).copy()
    d["gi"] = d.groupby(["season", "gsis_id"]).cumcount()
    ps = qualified(_player_seasons(d))
    keys = set(zip(ps.season, ps.gsis_id))
    d = d[[k in keys for k in zip(d.season, d.gsis_id)]]
    d["half"] = d["gi"] % 2
    names = ["pts_" + k for k in CAT_KEYS] + ["tier_" + t for t in TIERS] + ["total"]
    h = d.groupby(["season", "gsis_id", "pos", "half"])[names + ["defense_snaps"]].sum().reset_index()
    for n in names:
        h[n] = h[n] / h["defense_snaps"]                    # SUM(points)/SUM(snaps), never an average of rates
    w = h.pivot_table(index=["season", "gsis_id", "pos"], columns="half", values=names).dropna()
    out = {"games_mean": float(ps.games.mean()), "n_player_seasons": int(len(ps))}

    def one(sub, n):
        a, b = sub[(n, 0)], sub[(n, 1)]
        if len(sub) < 12 or a.std() == 0 or b.std() == 0:
            return {"r_half": None, "r_full": None, "n": int(len(sub))}
        r = float(np.corrcoef(a, b)[0, 1])
        return {"r_half": r, "r_full": (2 * r / (1 + r)) if r > -0.99 else None, "n": int(len(sub))}

    allr = {}
    dem = w.copy()
    for n in names:                                         # position-demean so position differences are not "stability"
        for hh in (0, 1):
            pm = pd.concat([w[(n, 0)], w[(n, 1)]]).groupby(level="pos").mean()
            dem[(n, hh)] = w[(n, hh)] - w.index.get_level_values("pos").map(pm).values
    for n in names:
        allr[n.replace("pts_", "").replace("tier_", "tier:")] = one(dem, n)
    out["all"] = allr
    out["by_pos"] = {p: {n.replace("pts_", "").replace("tier_", "tier:"): one(w[w.index.get_level_values("pos") == p], n)
                         for n in names} for p in POSITIONS}
    return out


def category_stats(df):
    """Pool: share of points by category, correlation of each category's PPG with total PPG, category x category
    correlation of per-snap rates, snap share vs PPG. Player-seasons that qualify (>=6 games, >=25% snaps)."""
    ps = qualified(_player_seasons(df))
    out = {"n": int(len(ps)), "share": {}, "corr_total": {}, "snap_corr": {}, "tier_share": {}, "cv": {}}
    for p in POSITIONS:
        s = ps[ps.pos == p]
        if len(s) < 8:
            continue
        tot = s["total"].sum()
        out["share"][p] = {k: float(s["pts_" + k].sum() / tot) if tot else None for k in CAT_KEYS}
        out["tier_share"][p] = {t: float(s["tier_" + t].sum() / tot) if tot else None for t in TIERS}
        ppg = s["total"] / s["games"]
        out["corr_total"][p] = {}
        for k in CAT_KEYS + ["tier:" + t for t in TIERS]:
            col = ("pts_" + k) if k in CAT_KEYS else ("tier_" + k[5:])
            x = s[col] / s["games"]
            out["corr_total"][p][k] = float(np.corrcoef(x, ppg)[0, 1]) if x.std() > 0 else None
        out["snap_corr"][p] = {"season": float(np.corrcoef(s["avg_pct"], ppg)[0, 1]), "n": int(len(s))}
        g = df[(df.pos == p)]
        gq = g[g.set_index(["season", "gsis_id"]).index.isin(list(zip(s.season, s.gsis_id)))]
        out["snap_corr"][p]["game"] = float(np.corrcoef(gq["defense_pct"].fillna(0), gq["total"])[0, 1])
        # weekly volatility of each tier: stdev of game points / mean, over qualifying players' games
        cv = {}
        for t in TIERS + ("total",):
            col = "tier_" + t if t != "total" else "total"
            m = gq[col].mean()
            cv[t] = float(gq[col].std() / m) if m else None
        out["cv"][p] = cv
    # category x category, per-snap rates, position-demeaned
    rate = ps.copy()
    for k in CAT_KEYS:
        rate["r_" + k] = rate["pts_" + k] / rate["snaps"]
        rate["r_" + k] -= rate.groupby("pos")["r_" + k].transform("mean")
    cols = ["r_" + k for k in CAT_KEYS]
    cm = rate[cols].corr()
    out["matrix"] = {"keys": CAT_KEYS, "values": [[None if pd.isna(cm.loc[a, b]) else float(cm.loc[a, b]) for b in cols] for a in cols]}
    return out


# ------------------------------------------------------------------------------------------- projection
def shrink_k(rel, tier):
    """k in w = g/(g+k): from the tier's full-season reliability at the mean games analysed (clipped)."""
    r = rel["all"].get("tier:" + tier, {}).get("r_full")
    r = min(max(r if r is not None else 0.3, 0.05), 0.95)
    return rel["games_mean"] * (1 - r) / r


def _weighted(vals):
    """Recency-weighted mean of the last len(RECENCY) values (newest last in `vals`)."""
    v = list(vals)[-len(RECENCY):][::-1]
    w = RECENCY[:len(v)]
    return sum(a * b for a, b in zip(v, w)) / sum(w) if v else None


def player_table(df, asof, rel, season=SEASON, played_teams=None):
    """Rows for every player with a game this season before week `asof`. `played_teams` = {week: set(team)} for the
    missed-game and bye flags. Pure function of `df` (rows with week < asof only are read)."""
    d = df[(df.season == season) & (df.week < asof)].sort_values(["gsis_id", "week"])
    if d.empty:
        return []
    pos_rate = {}
    qual = d.groupby("gsis_id").agg(g=("week", "count"), pct=("defense_pct", "mean"))
    qids = set(qual[(qual.g >= MIN_GAMES) & (qual.pct >= MIN_AVG_SNAP)].index)
    dq = d[d.gsis_id.isin(qids)]
    for p in POSITIONS:
        s = dq[dq.pos == p]
        sn = s["defense_snaps"].sum()
        pos_rate[p] = {t: (s["tier_" + t].sum() / sn if sn else 0.0) for t in TIERS}
    ks = {t: shrink_k(rel, t) for t in TIERS}
    rows = []
    for gid, g in d.groupby("gsis_id"):
        last = g.iloc[-1]
        pos = last["pos"]
        n = len(g)
        pcts = [x for x in g["defense_pct"].tolist() if x is not None and not pd.isna(x)]
        weeks = g["week"].tolist()
        avg = float(np.mean(pcts)) if pcts else None
        last3 = float(np.mean(pcts[-3:])) if pcts else None
        prior = pcts[-6:-3]
        delta = (last3 - float(np.mean(prior))) if (len(pcts) >= 5 and len(prior) >= 2) else None
        trend = "new" if delta is None else ("up" if delta >= TREND_POINTS else "down" if delta <= -TREND_POINTS else "flat")
        # expected snaps: recency-weighted share x the team's defensive snaps per game
        exp_pct = _weighted(pcts)
        recent = g.tail(len(RECENCY))
        ts = [s / p for s, p in zip(recent["defense_snaps"], recent["defense_pct"]) if p and not pd.isna(p) and p > 0]
        team_snaps = float(np.mean(ts)) if ts else None
        exp_snaps = exp_pct * team_snaps if (exp_pct is not None and team_snaps) else None
        snaps = float(g["defense_snaps"].sum())
        proj, comp = None, {}
        if exp_snaps is not None and snaps > 0:
            for t in TIERS:
                w = n / (n + ks[t])
                rate = w * (g["tier_" + t].sum() / snaps) + (1 - w) * pos_rate[pos][t]
                comp[t] = float(rate * exp_snaps)
            proj = sum(comp.values())
        tot = g["total"].tolist()
        tiers_sum = {t: float(g["tier_" + t].sum()) for t in TIERS}
        total_pts = float(g["total"].sum())
        last_games = tot[-8:]
        spark = {int(w): (None if pd.isna(p) else float(p)) for w, p in zip(weeks, g["defense_pct"])}
        team = last["team"]
        missed = bool(played_teams and team in played_teams.get(asof - 1, set()) and weeks[-1] < asof - 1)
        rows.append({
            "gsis_id": gid, "mfl_id": last["mfl_id"], "name": last["name"], "pos": pos, "team": team,
            "games": n, "snap_avg": avg, "snap_last3": last3, "snap_delta": delta, "trend": trend,
            "snap_by_week": spark, "last_week": int(weeks[-1]), "missed_last": missed,
            "exp_snap_pct": exp_pct, "exp_snaps": exp_snaps,
            "ppg": total_pts / n, "points": total_pts,
            "tier_ppg": {t: tiers_sum[t] / n for t in TIERS},
            "cat_ppg": {k: float(g["pts_" + k].sum() / n) for k in CAT_KEYS},
            "stable_share": (tiers_sum["stable"] / total_pts) if total_pts > 0 else None,
            "volatile_share": (tiers_sum["volatile"] / total_pts) if total_pts > 0 else None,
            "proj": proj, "proj_tier": comp or None,
            "p20": float(np.percentile(last_games, 20)) if len(last_games) >= 5 else None,
            "p80": float(np.percentile(last_games, 80)) if len(last_games) >= 5 else None,
            "last3_ppg": float(np.mean(tot[-3:])), "in_pool": gid in qids,
        })
    return rows


def style_labels(rows):
    """Floor / Balanced / Big-play from the pool's own quartiles of stable share (declared rule, not a model)."""
    sh = [r["stable_share"] for r in rows if r["in_pool"] and r["stable_share"] is not None]
    if len(sh) < 8:
        return
    q1, q3 = np.percentile(sh, 25), np.percentile(sh, 75)
    for r in rows:
        s = r["stable_share"]
        r["style"] = None if s is None else ("Floor" if s >= q3 else "Big-play" if s <= q1 else "Balanced")


# ----------------------------------------------------------------------------------------------- context
def played_teams(conn, season=SEASON):
    out = {}
    for w, h, a in conn.execute("SELECT week, home_team, away_team FROM core_schedule WHERE season = ? AND game_type = 'REG'", (season,)):
        out.setdefault(int(w), set()).update([h, a])
    return out


def ownership(conn, league_id, season=SEASON):
    """{gsis: status} for MY pool in this league: mine / taken (owner names) / free. A player owned only outside my
    pool, or owned fewer times than the pool's capacity (rostersPerPlayer), is available to me."""
    rows = [tuple(r) for r in conn.execute(
        "SELECT gsis_id, franchise_id, franchise_name, is_mine, pool_id, pool_capacity, roster_status FROM mart_roster_ownership "
        "WHERE season = ? AND league_id = ? AND platform = 'mfl'", (season, league_id))]
    mine_pools = {r[4] for r in rows if r[3]}
    my_pool = next(iter(mine_pools), None)
    by = {}
    for gid, fid, fname, is_mine, pool, cap, rs in rows:
        if gid is None or pool != my_pool:
            continue
        e = by.setdefault(gid, {"owners": [], "cap": cap or 1, "mine": False, "status": None})
        e["owners"].append(fname)
        if is_mine:
            e["mine"], e["status"] = True, rs
    out = {}
    for gid, e in by.items():
        if e["mine"]:
            out[gid] = {"status": "mine", "slot": e["status"]}
        elif len(e["owners"]) >= e["cap"]:
            out[gid] = {"status": "taken", "owners": e["owners"][:2]}
    return out, my_pool


def lineup_rules(conn, league_id):
    slots = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT position, min_slots, max_slots FROM mart_mfl_position_slots WHERE league_id = ?", (league_id,))}
    lz = conn.execute("SELECT idp_starters, pool_teams, rosters_per_player FROM mart_mfl_lineup_size WHERE league_id = ?",
                      (league_id,)).fetchone()
    idp_total = int(lz[0]) if lz else None
    slots = {p: v for p, v in slots.items() if p in POSITIONS}
    mins = sum(v[0] for v in slots.values())
    return {"slots": slots, "idp_total": idp_total, "flex": (idp_total - mins) if idp_total is not None else None}


def best_lineup(rows, lr):
    """Fill each position's minimum with the top start scores, then the flex slots from positions whose max exceeds min."""
    cand = sorted([r for r in rows if r.get("proj") is not None], key=lambda r: -r["proj"])
    chosen, used = [], set()
    for p, (mn, _mx) in lr["slots"].items():
        for r in [c for c in cand if c["pos"] == p][:mn]:
            chosen.append({**_brief(r), "slot": p})
            used.add(r["gsis_id"])
    flex = lr["flex"] or 0
    eligible = {p for p, (mn, mx) in lr["slots"].items() if mx > mn}
    taken = {p: sum(1 for c in chosen if c["pos"] == p) for p in lr["slots"]}
    for r in cand:
        if flex <= 0:
            break
        if r["gsis_id"] in used or r["pos"] not in eligible or taken[r["pos"]] >= lr["slots"][r["pos"]][1]:
            continue
        chosen.append({**_brief(r), "slot": "FLEX"})
        used.add(r["gsis_id"])
        taken[r["pos"]] += 1
        flex -= 1
    return chosen


def _brief(r):
    return {k: r[k] for k in ("gsis_id", "name", "pos", "team", "proj", "trend", "stable_share", "style")}


# ---------------------------------------------------------------------------------------------- backtest
def backtest(df, rel2025, first_week=4, last_week=None, played=None):
    """Walk-forward on SEASON: for each week W the table uses only games before W, and the reliability came from 2025
    alone. Scored against the points actually made at W by players who played at W (who plays is not known beforehand)."""
    last_week = last_week or int(df[df.season == SEASON]["week"].max())
    recs = []
    for w in range(first_week, last_week + 1):
        rows = [r for r in player_table(df, w, rel2025, played_teams=played) if r["in_pool"] and r["proj"] is not None]
        act = df[(df.season == SEASON) & (df.week == w)].set_index("gsis_id")["total"]
        for r in rows:
            if r["gsis_id"] in act.index:
                recs.append({"week": w, "pos": r["pos"], "act": float(act[r["gsis_id"]]), "proj": r["proj"],
                             "ppg": r["ppg"], "last3": r["last3_ppg"]})
    if not recs:
        return None
    b = pd.DataFrame(recs)

    def sp(x, y):
        return float(x.corr(y, method="spearman"))

    out = {"n": int(len(b)), "weeks": [first_week, last_week], "methods": {}}
    for name, col in (("start_score", "proj"), ("season_ppg", "ppg"), ("last3_ppg", "last3")):
        within = [sp(g[col], g["act"]) for _, g in b.groupby(["week", "pos"]) if len(g) >= 10]
        out["methods"][name] = {"spearman_pooled": sp(b[col], b["act"]), "spearman_within_pos_week": float(np.mean(within)),
                                "mae": float((b[col] - b["act"]).abs().mean()), "bias": float((b[col] - b["act"]).mean())}
    # top-quartile precision: of the top 25% projected in each position-week, the share that finished in the top 25% actual
    for name, col in (("start_score", "proj"), ("season_ppg", "ppg"), ("last3_ppg", "last3")):
        hits = tot = 0
        for _, g in b.groupby(["week", "pos"]):
            if len(g) < 12:
                continue
            k = max(1, len(g) // 4)
            top_p = set(g.nlargest(k, col).index)
            top_a = set(g.nlargest(k, "act").index)
            hits += len(top_p & top_a)
            tot += k
        out["methods"][name]["top_quartile_hit"] = hits / tot if tot else None
    return out


# ------------------------------------------------------------------------------------------------- build
def build_league(conn, league_id, asof=None):
    df, info = load_frame(conn, league_id)
    cur = df[df.season == SEASON]
    through = int(cur["week"].max())
    asof = asof or through + 1
    asof = min(max(asof, 2), through + 1)
    played = played_teams(conn)
    rel = split_half(df[df.week < 99], (2025, SEASON))          # production: both seasons
    rel25 = split_half(df, (2025,))                              # walk-forward: 2025 only
    rows = player_table(df, asof, rel, played_teams=played)
    style_labels(rows)
    own, my_pool = ownership(conn, league_id)
    bye = {t for t in {r["team"] for r in rows} if played.get(asof) is not None and t not in played[asof]}
    for r in rows:
        r["owner"] = own.get(r["gsis_id"], {"status": "free"})
        r["bye"] = r["team"] in bye
    lr = lineup_rules(conn, league_id)
    mine = [r for r in rows if r["owner"]["status"] == "mine" and r["proj"] is not None and not r["bye"]]
    free = [r for r in rows if r["owner"]["status"] == "free" and r["in_pool"] and r["proj"] is not None and not r["bye"]]
    league = conn.execute("SELECT name FROM mart_mfl_leagues WHERE league_id = ?", (league_id,)).fetchone()
    return _clean({
        "league_id": league_id, "league": league[0] if league else league_id, "season": SEASON, "through_week": through,
        "asof": asof, "my_pool": my_pool, "info": info, "reconcile": reconcile(conn, league_id, df),
        "reliability": rel, "categories": category_stats(df),
        "cats": [{"key": k, "label": lab, "tier": t} for k, lab, t, _ in CATS],
        "players": rows, "lineup_rules": {"slots": lr["slots"], "idp_total": lr["idp_total"], "flex": lr["flex"]},
        "my_lineup": best_lineup(mine, lr),
        "free_targets": sorted([_brief(r) for r in free], key=lambda r: -r["proj"])[:25],
        "backtest": backtest(df, rel25, played=played) if asof == through + 1 else None,
        "weights": {"recency": RECENCY, "min_avg_snap": MIN_AVG_SNAP, "min_games": MIN_GAMES, "trend_points": TREND_POINTS,
                    "shrink_k": {t: shrink_k(rel, t) for t in TIERS}},
    })
