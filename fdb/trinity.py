"""Trinity Score, as ddfantasyfootball.com's Trinity Tracker page computes it.

DD does not serve a per-week score: its page builds one in the browser from
`trinity_ftn_aggregates_weeks` (our core_trinity_ftn_aggregates). This module is a line-by-line
port of that page's functions (read from the served bundle `TrinityScoreChart-*.js`, 2026-10-01:
`Ye` the score, `Ge` the metrics, `B` the blend, `Re` the tier, `I` the target floor, `L`/`R`/`z`
the statistics). It is DD's formula as ported, NOT a stored source field, so it lives only in
mart_trinity_*, never in a core table (REBUILD_DESIGN §1 rule 4: rates and scores at read time).

Fidelity notes: JavaScript's Math.round rounds halves UP (Python's round() rounds half-even), the
std is the SAMPLE std (n-1) with 1 substituted for 0, sums are plain left-to-right adds (Python's
sum() is compensated since 3.12), and every z is clamped to +-2.5.

  score = 5 + .36 z(first_downs) + .30 z(yprr) + .34 z(yac/game) + .38 z(rec/game) + .29 z(air-yard share)
  clamped to 0..10, 2 dp. z uses the WR+TE population of the window; RB are scored against it.
"""
import math
from collections import defaultdict


CLAMP = 2.5
WEIGHTS = {"fd": 0.36, "yprr": 0.30, "yacg": 0.34, "recg": 0.38, "ays": 0.29}
BASE_TARGETS = 5          # `Ue`: the floor for a full 17-game window, scaled down for shorter windows
FULL_WINDOW = 17
BANDS = {"WR": [("Elite", 7.7), ("Above League Average", 6.7), ("League Average", 5.5), ("Below League Average", 4.9)],
         "TE": [("Elite", 7.2), ("Above League Average", 6.6), ("League Average", 5.5), ("Below League Average", 5.1)]}
POSITIONS = ("WR", "TE", "RB")
Z_FIELDS = ("first_downs", "yprr", "yac_per_game", "rec_per_game", "air_yard_share")


def js_round(x: float) -> int:
    """JavaScript Math.round: halves round toward +infinity."""
    return math.floor(x + 0.5)


def _num(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def min_targets(window_games: float) -> int:
    t = max(1, min(FULL_WINDOW, js_round(window_games or FULL_WINDOW))) / FULL_WINDOW
    return max(1, js_round(BASE_TARGETS * t))


def metrics(row: dict) -> dict:
    games = max(_num(row.get("games")), 1)
    routes = max(_num(row.get("routes")), 1)
    team_ay = _num(row.get("team_air_yards"))
    return {"yprr": _num(row.get("rec_yards")) / routes,
            "rec_per_game": _num(row.get("rec")) / games,
            "yac_per_game": _num(row.get("yac")) / games,
            "air_yard_share": _num(row.get("player_air_yards")) / team_ay if team_ay > 0 else 0.0,
            "first_downs": _num(row.get("first_downs"))}


def _mean_std(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 1.0
    total = 0.0
    for x in xs:
        total += x
    mean = total / n
    ss = 0.0
    for x in xs:
        ss += (x - mean) ** 2
    std = math.sqrt(ss / max(n - 1, 1))
    return mean, (std or 1.0)


def _clamp(x: float) -> float:
    return max(-CLAMP, min(CLAMP, x)) if math.isfinite(x) else 0.0


def tier(pos: str, score: float) -> str:
    band = BANDS["TE" if pos == "TE" else "WR"]   # RB are banded with WR (`Le`)
    if not math.isfinite(score):
        return "Depth"
    return next((label for label, lo in band if score >= lo), "Depth")


def score_window(rows: list[dict], window_games: float) -> list[dict]:
    """rows: aggregate dicts (core_trinity_ftn_aggregates columns, summed over the window).
    window_games: DD passes min(weeks in window, most games any player has in it).
    -> one dict per qualifying player: {row, **metrics, z_*, trinity_score, tier, position_rank}."""
    floor = min_targets(window_games)
    kept = []
    for r in rows:                                       # Xe's pre-filter, then Ye's
        if _num(r.get("games")) > 0 and _num(r.get("routes")) > 0 \
                and str(r.get("pos") or "").upper() in POSITIONS and _num(r.get("targets")) >= floor:
            kept.append((r, metrics(r)))
    pool = [m for r, m in kept if str(r["pos"]).upper() in ("WR", "TE")]
    if not pool:
        return []
    stats = {f: _mean_std([m[f] for m in pool]) for f in Z_FIELDS}
    out = []
    for r, m in kept:
        z = {f: _clamp((m[f] - stats[f][0]) / stats[f][1]) for f in Z_FIELDS}
        raw = (5 + WEIGHTS["fd"] * z["first_downs"] + WEIGHTS["yprr"] * z["yprr"] + WEIGHTS["yacg"] * z["yac_per_game"]
               + WEIGHTS["recg"] * z["rec_per_game"] + WEIGHTS["ays"] * z["air_yard_share"])
        score = js_round(max(0.0, min(10.0, raw)) * 100) / 100
        pos = str(r["pos"]).upper()
        out.append({"row": r, **m, **{f"z_{f}": v for f, v in z.items()}, "trinity_score": score, "tier": tier(pos, score)})
    by_pos = defaultdict(list)
    for o in out:
        by_pos[str(o["row"]["pos"]).upper()].append(o)
    for lst in by_pos.values():
        for i, o in enumerate(sorted(lst, key=lambda o: -o["trinity_score"]), 1):   # stable, like Array.sort
            o["position_rank"] = i
    return out


SUM_FIELDS = ("games", "routes", "targets", "rec", "rec_yards", "yac", "rec_td", "first_downs", "player_air_yards", "team_air_yards")
COLS = ("season", "season_type", "week", "sleeper_id", "player_gsis_id", "gsis_id", "full_name", "team", "position", "games",
        "routes", "targets", "rec", "rec_yards", "rec_td", "first_downs", "yprr", "rec_per_game", "yac_per_game", "air_yard_share",
        "z_first_downs", "z_yprr", "z_yac_per_game", "z_rec_per_game", "z_air_yard_share", "trinity_score", "tier", "position_rank")


def _mart_rows(season: int, week: int, scored: list[dict], gsis_of: dict) -> list[tuple]:
    out = []
    for o in scored:
        r = o["row"]
        out.append((season, "REG", week, r["sleeper_id"], r["player_gsis_id"], gsis_of.get(r["sleeper_id"]), r.get("full_name"),
                    r["team"], str(r["pos"]).upper(), int(_num(r["games"])), int(_num(r["routes"])), int(_num(r["targets"])),
                    int(_num(r["rec"])), int(_num(r["rec_yards"])), int(_num(r["rec_td"])), int(_num(r["first_downs"])),
                    o["yprr"], o["rec_per_game"], o["yac_per_game"], o["air_yard_share"], o["z_first_downs"], o["z_yprr"],
                    o["z_yac_per_game"], o["z_rec_per_game"], o["z_air_yard_share"], o["trinity_score"], o["tier"], o["position_rank"]))
    return out


def window_of(weeks: list[list[dict]]) -> tuple[list[dict], float]:
    """Sum the per-week rows of one player into the window rows DD's RPC returns, and the window_games
    DD's page passes on: min(weeks asked, most games any player has).

    Verified against DD's own p_weeks=1..17 call for 2025 (499 players, every field identical): counts and
    player air yards are plain sums over the player's weeks; `team` is his LATEST team; and `team_air_yards`
    is NOT summed over his own rows but is that latest team's air yards summed over EVERY window week the
    team has data for, including weeks he missed (480 single-team and 19 traded players all match)."""
    acc: dict[str, dict] = {}
    team_week: dict[str, dict[int, float]] = defaultdict(dict)
    for i, rows in enumerate(weeks):
        for r in rows:
            team_week[r["team"]][i] = _num(r.get("team_air_yards"))
            a = acc.get(r["player_gsis_id"])
            if a is None:
                a = acc[r["player_gsis_id"]] = {**r, **{f: 0 for f in SUM_FIELDS}}
            for f in SUM_FIELDS:
                if f != "team_air_yards":
                    a[f] += _num(r.get(f))
            a["team"], a["pos"] = r["team"], r["pos"]       # the latest week's team (a trade moves him)
    for a in acc.values():
        a["team_air_yards"] = sum(team_week[a["team"]].values())
    # DD's RPC returns rows ascending by player_gsis_id (observed on every call); Array.sort is stable, so that
    # order decides the position_rank of players tied on score
    rows = sorted(acc.values(), key=lambda r: r["player_gsis_id"])
    most = max([1] + [int(_num(r["games"])) for r in rows])
    return rows, min(len(weeks), most)


def build(conn) -> dict:
    gsis_of = {r[0]: r[1] for r in conn.execute("SELECT source_id, gsis_id FROM player_ids WHERE source = 'sleeper'")}
    cols = ["player_gsis_id", "full_name", "pos", "sleeper_id", "team", *SUM_FIELDS]
    wk, thru, stats = [], [], {"players": 0, "unresolved": 0, "gsis_mismatch": 0}
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM core_trinity_ftn_aggregates ORDER BY season")]
    for s in seasons:
        by_week: dict[int, list[dict]] = defaultdict(list)
        for r in conn.execute(f"SELECT week, {', '.join(cols)} FROM core_trinity_ftn_aggregates WHERE season = ? "
                              "ORDER BY week, rowid", (s,)):
            by_week[r["week"]].append({c: r[c] for c in cols})
        weeks = sorted(by_week)
        for w in weeks:
            wk += _mart_rows(s, w, score_window(*window_of([by_week[w]])), gsis_of)
            # season to date = weeks 1..w. It exists only while every week from 1 is loaded: a missing week
            # (a documented source defect, loaders/ddff.py SOURCE_DEFECTS) ends the series rather than being bridged
            if all(x in by_week for x in range(1, w + 1)):
                thru += _mart_rows(s, w, score_window(*window_of([by_week[x] for x in range(1, w + 1)])), gsis_of)
    for t in wk:
        stats["players"] += 1
        stats["unresolved"] += t[5] is None
        stats["gsis_mismatch"] += t[5] is not None and t[5] != t[4]
    fails = checks(wk, thru, stats)
    marks = ",".join("?" * len(COLS))
    conn.execute("BEGIN")
    try:
        for tbl, rows in (("mart_trinity_week", wk), ("mart_trinity_through_week", thru)):
            conn.execute(f"DELETE FROM {tbl}")
            conn.executemany(f"INSERT INTO {tbl} ({', '.join(COLS)}) VALUES ({marks})", rows)
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"failures": fails, "summary": _summary(conn, wk, thru, stats)}


def checks(wk: list[tuple], thru: list[tuple], stats: dict) -> list[str]:
    fails = []
    i = COLS.index("trinity_score")
    for name, rows in (("mart_trinity_week", wk), ("mart_trinity_through_week", thru)):
        bad = [r for r in rows if not 0 <= r[i] <= 10]
        if bad:
            fails.append(f"{name}: {len(bad)} scores outside 0-10")
    if wk and stats["players"] and stats["gsis_mismatch"] > 0.02 * stats["players"]:
        fails.append(f"DD's own player_gsis_id disagrees with player_ids(sleeper) on {stats['gsis_mismatch']} of "
                     f"{stats['players']} player-weeks (>2%): an id table is wrong")
    return fails


def _summary(conn, wk, thru, stats) -> str:
    from .loaders.ddff import SOURCE_DEFECTS
    s = f"{len(wk)} player-weeks, {len(thru)} season-to-date rows; {stats['unresolved']} unresolved to gsis, " \
        f"{stats['gsis_mismatch']} where DD's gsis differs from player_ids"
    s += f"; {len(SOURCE_DEFECTS)} weeks withheld as DD source defects ({', '.join(f'{a} wk{c}' for a, _, c in sorted(SOURCE_DEFECTS))})"
    # How closely the ported weeks-1..17 score reproduces DD's stored season score (full 17-week windows only;
    # ids that DD stored twice are skipped).
    # Reported, not gated: the live parity gate is recorded in REBUILD_LOG.md.
    diffs = [abs(a - b) for a, b in conn.execute("""SELECT t.trinity_score, c.trinity_score FROM mart_trinity_through_week t
                 JOIN core_trinity_scores c ON c.season = t.season AND c.sleeper_id = t.sleeper_id
                 WHERE t.week = 17
                   AND c.sleeper_id IN (SELECT sleeper_id FROM core_trinity_scores WHERE sleeper_id IS NOT NULL
                                        GROUP BY season, sleeper_id HAVING COUNT(*) = 1)""")]
    if diffs:
        diffs.sort()
        s += f"; vs DD stored season score: n={len(diffs)}, median |diff| {diffs[len(diffs) // 2]:.3f}, max {diffs[-1]:.3f}"
    return s
