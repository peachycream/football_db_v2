"""Phase 16b Stage 1 (PHASE16B_SPEC.md): the next-season outlook of NFL defenders -> mart_idp_outlook, _model, _exit (builder `idp_outlook.build`).

The model is the Phase 16a PRIMARY model (PHASE16A_SPEC.md; ops/phase16a_backtest.py), frozen: ridge on eight features (with their
missing indicators) of season N, target = league points in season N+1 (0 when the player has no row there), one fit per position
group, DT, S and CB only. The gate failed at DE and LB, so those rows carry `model` NULL and last year's points as the baseline rank.
Origin rule: the outlook for season N is trained only on candidates of seasons N' < N (their next season is closed by the end of N),
so every N from 2021 on holds the same out-of-time prediction the backtest made, and the newest closed N is the live outlook.
Only closed seasons are read (rule 7). Points, games, snaps and group come from `idp_prospect._season_points` (catch-all rules of
LEAGUE); the join key is gsis_id. Ridge is the numpy closed form (fdb does not import sklearn); tests pin it to sklearn's Ridge.
"""
import json
import math
from collections import defaultdict
from datetime import date

import numpy as np

from .idp_prospect import LEAGUE, _closed_seasons, _season_points
from .scoring import catch_all_rules

MODEL_ID = "ridge16a"
SNAP_FLOOR = 300
FIRST_N = 2016
FIRST_OUTLOOK_N = 2021
GROUPS = ("DE", "DT", "LB", "S", "CB")
MODEL_GROUPS = ("DT", "S", "CB")
GRID = (3.0, 10.0, 30.0, 100.0)
FEATURES = ["ppg_N", "log_snaps_N", "games_N", "age", "exp_yrs", "has_draft_year", "ppg_prev", "has_prev", "et_gap_pg", "has_et",
            "es_gap_pg", "has_es"]
AGE_BANDS = ("<25", "25-27", "28-30", "31+")
MIN_NEWEST = 60          # candidates per model group in the newest N
MIN_TRAIN = 400          # training rows per model group in the newest N
MIN_FIT, MIN_TEST = 100, 10   # the backtest's guards
RANGE_PAD = 0.25
# PHASE16A_SPEC result of record: pooled out-of-time Spearman of PRIMARY against points_next, N = 2021-2024 (REBUILD_LOG.md, Phase 16a).
PARITY_16A = {"DT": 0.555, "S": 0.499, "CB": 0.498}
PARITY_TOL = 0.0006
PARITY_NS = (2021, 2022, 2023, 2024)


# ---- the model (pure) ----------------------------------------------------------------------------------------------------
def features(r) -> list[float]:
    """The eight features and their indicators for one candidate row (a dict of mart columns); NaN where missing."""
    nan = float("nan")
    dy, games = r["draft_year"], r["games_n"]
    pg_prev = r["points_prev"] / r["games_prev"] if r["games_prev"] and r["games_prev"] > 0 else nan
    return [r["points_n"] / games, math.log(r["snaps_n"]), float(games),
            r["age_next"] if r["age_next"] is not None else nan,
            float(r["season_n"] + 1 - dy) if dy else nan, float(bool(dy)),
            pg_prev, float(not math.isnan(pg_prev)),
            r["et_gap"] / games if r["et_gap"] is not None else nan, float(r["et_gap"] is not None),
            r["es_gap"] / games if r["es_gap"] is not None else nan, float(r["es_gap"] is not None)]


def matrix(rows) -> np.ndarray:
    return np.array([features(r) for r in rows], dtype=float).reshape(len(rows), len(FEATURES))


def design_fit(x: np.ndarray):
    """Median fill (an all-missing column fills 0), then standardise: (filled X, median, mean, scale). Scale 1 where constant."""
    med = np.array([np.nanmedian(x[:, j]) if np.isfinite(x[:, j]).any() else 0.0 for j in range(x.shape[1])])
    a = np.where(np.isnan(x), med, x)
    a = np.where(np.isnan(a), 0.0, a)
    mean, scale = a.mean(axis=0), a.std(axis=0)
    scale = np.where(scale < 10 * np.finfo(float).eps, 1.0, scale)
    return (a - mean) / scale, med, mean, scale


def design_apply(x: np.ndarray, med, mean, scale) -> np.ndarray:
    a = np.where(np.isnan(x), med, x)
    a = np.where(np.isnan(a), 0.0, a)
    return (a - mean) / scale


def ridge_fit(z: np.ndarray, y: np.ndarray, alpha: float):
    """Closed-form ridge on standardised features, unpenalised intercept: (intercept, coef)."""
    ym = float(y.mean())
    coef = np.linalg.solve(z.T @ z + alpha * np.eye(z.shape[1]), z.T @ (y - ym))
    return ym, coef


def pick_alpha(rows, y: np.ndarray) -> float:
    """Leave-one-transition-out squared error over GRID inside the training rows only (the backtest's rule, ties to the earlier alpha)."""
    ns = np.array([r["season_n"] for r in rows])
    x = matrix(rows)
    uniq = sorted(set(ns.tolist()))
    if len(uniq) < 2:
        return 30.0
    best, err = GRID[2], math.inf
    for a in GRID:
        e = []
        for k in uniq:
            tr, va = ns != k, ns == k
            if not va.any() or tr.sum() < 50:
                continue
            z, med, mean, scale = design_fit(x[tr])
            ic, coef = ridge_fit(z, y[tr], a)
            pred = ic + design_apply(x[va], med, mean, scale) @ coef
            e.append(float(np.mean((pred - y[va]) ** 2)))
        if e and np.mean(e) < err:
            best, err = a, float(np.mean(e))
    return best


def fit(train_rows):
    """Fit one position group: dict(alpha, intercept, coef, median, mean, scale)."""
    y = np.array([r["points_next_actual"] for r in train_rows], dtype=float)
    alpha = pick_alpha(train_rows, y)
    z, med, mean, scale = design_fit(matrix(train_rows))
    ic, coef = ridge_fit(z, y, alpha)
    return {"alpha": alpha, "intercept": ic, "coef": coef, "median": med, "mean": mean, "scale": scale}


def predict(m, rows) -> np.ndarray:
    return m["intercept"] + design_apply(matrix(rows), m["median"], m["mean"], m["scale"]) @ m["coef"]


def age_band(age):
    if age is None or (isinstance(age, float) and math.isnan(age)):
        return None
    return "<25" if age < 25 else "25-27" if age < 28 else "28-30" if age < 31 else "31+"


def best_rank(values) -> list[int]:
    """1 + the number of strictly greater values: ties share the best rank."""
    return [1 + sum(1 for w in values if w > v) for v in values]


def spearman(a, b) -> float:
    def avg_rank(v):
        v = np.asarray(v, dtype=float)
        order = np.argsort(v, kind="mergesort")
        r = np.empty(len(v))
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return r
    return float(np.corrcoef(avg_rank(a), avg_rank(b))[0, 1])


# ---- the panel ----------------------------------------------------------------------------------------------------------
def panel(conn, closed, rules) -> tuple[list[dict], int]:
    """Candidate player-seasons for N in FIRST_N..newest closed: (rows, player-seasons dropped for lacking a gsis_id)."""
    closed = sorted(closed)
    rows_by = _season_points(conn, closed, rules)
    by, dropped = defaultdict(dict), 0
    for (s, key), a in rows_by.items():
        if not a["gsis"]:
            dropped += 1
            continue
        if s in by[a["gsis"]]:
            raise ValueError(f"{a['gsis']}: two PFF keys in {s}")
        by[a["gsis"]][s] = a
    prof = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT gsis_id, birth_date, draft_year FROM mart_player_profile")}
    et = {(r[0], r[1]): r[2] for r in conn.execute(
        """SELECT season, gsis_id, SUM(actual_tackles_run + actual_tackles_pass - expected_tackles_run - expected_tackles_pass)
           FROM mart_idp_expected_tackles_week WHERE season_type = 'REG' GROUP BY season, gsis_id""")}
    es = {(r[0], r[1]): r[2] for r in conn.execute(
        """SELECT season, gsis_id, SUM(sacks - expected_sacks) FROM mart_idp_expected_sacks_week
           WHERE season_type = 'REG' GROUP BY season, gsis_id""")}
    closed_set = set(closed)
    out = []
    for gsis, seasons in by.items():
        bd, dy = prof.get(gsis, (None, None))
        for n in range(FIRST_N, max(closed) + 1):
            a = seasons.get(n)
            if a is None or n not in closed_set or a["snaps"] < SNAP_FLOOR or a["group"] not in GROUPS or a["games"] <= 0:
                continue
            prev, nxt = seasons.get(n - 1), seasons.get(n + 1)
            out.append(dict(
                gsis_id=gsis, season_n=n, season_next=n + 1, position_group=a["group"], points_n=a["points"], games_n=a["games"],
                snaps_n=a["snaps"], points_prev=prev["points"] if prev else None, games_prev=prev["games"] if prev else None,
                et_gap=et.get((n, gsis)), es_gap=es.get((n, gsis)),
                age_next=(date(n + 1, 9, 1) - date.fromisoformat(bd[:10])).days / 365.25 if bd else None,
                draft_year=dy, model=None, pred_points_next=None, rank_pred=None, rank_last=0,
                points_next_actual=(nxt["points"] if nxt else 0.0) if (n + 1) in closed_set else None))
    out.sort(key=lambda r: (r["season_n"], r["position_group"], r["gsis_id"]))
    return out, dropped


def assemble(rows) -> tuple[list[dict], list[dict], list[tuple], list[str]]:
    """Fill model, prediction and ranks. Returns (rows from FIRST_OUTLOOK_N, model rows, exit rows, failures)."""
    fails, models, exits = [], [], []
    by = defaultdict(list)
    for r in rows:
        by[(r["season_n"], r["position_group"])].append(r)
    seasons = sorted({r["season_n"] for r in rows if r["season_n"] >= FIRST_OUTLOOK_N})
    newest = max((r["season_n"] for r in rows), default=None)
    for n in seasons:
        for g in GROUPS:
            test = by.get((n, g), [])
            train = [r for r in rows if r["position_group"] == g and r["season_n"] < n and r["points_next_actual"] is not None]
            for band in AGE_BANDS:
                inb = [r for r in train if age_band(r["age_next"]) == band]
                if inb:
                    exits.append((n, g, band, len(inb), sum(1 for r in inb if r["points_next_actual"] == 0)))
            if g in MODEL_GROUPS and len(train) >= MIN_FIT and len(test) >= MIN_TEST:
                m = fit(train)
                pred = predict(m, test)
                lo, hi = min(r["points_next_actual"] for r in train), max(r["points_next_actual"] for r in train)
                pad = RANGE_PAD * (hi - lo)
                if not np.isfinite(pred).all() or pred.min() < lo - pad or pred.max() > hi + pad:
                    fails.append(f"{n} {g}: a prediction is not finite or outside the training targets {lo:.0f}..{hi:.0f} +-{RANGE_PAD:.0%}")
                for r, p in zip(test, pred):
                    r["model"], r["pred_points_next"] = MODEL_ID, float(p)
                for r, k in zip(test, best_rank([r["pred_points_next"] for r in test])):
                    r["rank_pred"] = k
                models.append(dict(season_n=n, position_group=g, model=MODEL_ID, n_train=len(train),
                                   first_train_n=min(r["season_n"] for r in train), last_train_n=max(r["season_n"] for r in train),
                                   alpha=m["alpha"], intercept=m["intercept"], features=json.dumps(FEATURES),
                                   coef=json.dumps(m["coef"].tolist()), median=json.dumps(m["median"].tolist()),
                                   mean=json.dumps(m["mean"].tolist()), scale=json.dumps(m["scale"].tolist())))
                if n == newest and (len(test) < MIN_NEWEST or len(train) < MIN_TRAIN):
                    fails.append(f"{n} {g}: {len(test)} candidates (floor {MIN_NEWEST}), {len(train)} training rows (floor {MIN_TRAIN})")
            elif g in MODEL_GROUPS and test:
                fails.append(f"{n} {g}: {len(train)} training rows and {len(test)} candidates, not enough for the model")
            for r, k in zip(test, best_rank([r["points_n"] for r in test])):
                r["rank_last"] = k
    return [r for r in rows if r["season_n"] >= FIRST_OUTLOOK_N], models, exits, fails


def parity_failures(rows) -> list[str]:
    """The 16a result of record: pooled N = 2021-2024 Spearman of the prediction against the actual next-season points."""
    if not all(any(r["season_n"] == n and r["points_next_actual"] is not None for r in rows) for n in PARITY_NS):
        return []   # a database that does not span the 16a window has nothing to be compared with
    fails = []
    for g, want in PARITY_16A.items():
        sel = [r for r in rows if r["position_group"] == g and r["season_n"] in PARITY_NS and r["model"] and r["points_next_actual"] is not None]
        if not sel:
            fails.append(f"parity: no {g} rows with a prediction and an actual for N {PARITY_NS[0]}-{PARITY_NS[-1]}")
            continue
        got = spearman([r["pred_points_next"] for r in sel], [r["points_next_actual"] for r in sel])
        if abs(got - want) > PARITY_TOL:
            fails.append(f"parity: {g} pooled Spearman {got:.4f}, the Phase 16a result of record is {want:.3f}")
    return fails


# ---- the builder --------------------------------------------------------------------------------------------------------
OUTLOOK_COLS = ["gsis_id", "season_n", "season_next", "position_group", "points_n", "games_n", "snaps_n", "points_prev", "games_prev",
                "et_gap", "es_gap", "age_next", "draft_year", "model", "pred_points_next", "rank_pred", "rank_last", "points_next_actual"]
MODEL_COLS = ["season_n", "position_group", "model", "n_train", "first_train_n", "last_train_n", "alpha", "intercept", "features", "coef",
              "median", "mean", "scale"]


def build(conn) -> dict:
    closed = _closed_seasons(conn)
    if not closed or not conn.execute("SELECT 1 FROM mart_player_allowed_week LIMIT 1").fetchone():
        for t in ("mart_idp_outlook", "mart_idp_outlook_model", "mart_idp_outlook_exit"):
            conn.execute(f"DELETE FROM {t}")
        return {"failures": [], "summary": "no closed season with defensive weeks loaded"}
    rules, _ = catch_all_rules(conn, LEAGUE)
    if not rules:
        return {"failures": [f"no mart_mfl_rules rows for league {LEAGUE}"], "summary": "no rules"}
    rows, dropped = panel(conn, closed, rules)
    out, models, exits, fails = assemble(rows)
    fails += parity_failures(rows)
    conn.execute("BEGIN")
    try:
        for t in ("mart_idp_outlook", "mart_idp_outlook_model", "mart_idp_outlook_exit"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany(f"INSERT INTO mart_idp_outlook ({', '.join(OUTLOOK_COLS)}) VALUES ({', '.join('?' * len(OUTLOOK_COLS))})",
                         [tuple(r[c] for c in OUTLOOK_COLS) for r in out])
        conn.executemany(f"INSERT INTO mart_idp_outlook_model ({', '.join(MODEL_COLS)}) VALUES ({', '.join('?' * len(MODEL_COLS))})",
                         [tuple(m[c] for c in MODEL_COLS) for m in models])
        conn.executemany("INSERT INTO mart_idp_outlook_exit (season_n, position_group, age_band, n, n_zero) VALUES (?,?,?,?,?)", exits)
        fails += checks(conn, closed)
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    newest = max(r["season_n"] for r in out) if out else None
    live = sum(1 for r in out if r["season_n"] == newest and r["model"])
    return {"failures": fails, "summary": f"{len(out)} candidate player-seasons N {FIRST_OUTLOOK_N}-{newest} ({dropped} without gsis_id dropped), "
                                          f"{len(models)} model fits, {live} live outlook rows for N {newest}, league {LEAGUE}"}


def checks(conn, closed) -> list[str]:
    fails, closed = [], set(closed)
    for season_n, season_next, snaps, actual, model, rank_pred, pred in conn.execute(
            "SELECT season_n, season_next, snaps_n, points_next_actual, model, rank_pred, pred_points_next FROM mart_idp_outlook"):
        if season_n not in closed or season_next != season_n + 1 or snaps < SNAP_FLOOR:
            fails.append(f"a row with season_n {season_n}, season_next {season_next}, snaps {snaps}")
            break
        if (actual is None) != (season_next not in closed):
            fails.append(f"points_next_actual is {'NULL' if actual is None else 'set'} but season {season_next} is "
                         f"{'closed' if season_next in closed else 'not closed'}")
            break
        if (rank_pred is not None or pred is not None) != (model is not None):
            fails.append("a prediction or rank_pred without a model, or a model without both")
            break
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_outlook WHERE rank_last < 1").fetchone()[0]
    if bad:
        fails.append(f"{bad} rows without a rank_last")
    bad = conn.execute("""SELECT COUNT(*) FROM mart_idp_outlook o WHERE rank_last != 1 + (SELECT COUNT(*) FROM mart_idp_outlook p
                          WHERE p.season_n = o.season_n AND p.position_group = o.position_group AND p.points_n > o.points_n)""").fetchone()[0]
    if bad:
        fails.append(f"{bad} rows whose rank_last disagrees with points_n")
    bad = conn.execute("""SELECT COUNT(*) FROM mart_idp_outlook o WHERE model IS NOT NULL AND rank_pred != 1 + (SELECT COUNT(*)
                          FROM mart_idp_outlook p WHERE p.season_n = o.season_n AND p.position_group = o.position_group
                          AND p.model IS NOT NULL AND p.pred_points_next > o.pred_points_next)""").fetchone()[0]
    if bad:
        fails.append(f"{bad} rows whose rank_pred disagrees with the prediction")
    bad = conn.execute("""SELECT COUNT(*) FROM mart_idp_outlook o WHERE model IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mart_idp_outlook_model m
                          WHERE m.season_n = o.season_n AND m.position_group = o.position_group)""").fetchone()[0]
    if bad:
        fails.append(f"{bad} predictions without a model row")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_outlook_exit WHERE n_zero > n OR n < 1").fetchone()[0]
    if bad:
        fails.append(f"{bad} exit cells with n_zero > n")
    return fails
