"""`fdb rebuild`: regenerate the database from data/raw + code, with the network
disabled (REBUILD_DESIGN §2.2).

Builds into a side file and swaps it in only if every load passed, so a failed
rebuild leaves the old database untouched. User-entered state (app_* tables) is
exported to app_state/*.csv first and re-imported after."""
import csv
import os

from . import config, db, http, loader as fw, raw, registry
from .builders import BUILDERS
from .loaders import get
from .timeutil import stamp, utcnow


def export_app_state(conn) -> list[str]:
    config.APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for t in db.data_tables(conn):
        if not t.startswith("app_"):
            continue
        cols = db.columns(conn, t)
        with open(config.APP_STATE_DIR / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(conn.execute(f"SELECT {', '.join(cols)} FROM {t} ORDER BY 1"))
        out.append(t)
    return out


def import_app_state(conn) -> list[str]:
    out = []
    for p in sorted(config.APP_STATE_DIR.glob("app_*.csv")):
        t = p.stem
        with open(p, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            cols = next(r)
            conn.execute("BEGIN")
            conn.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [[None if v == "" else v for v in row] for row in r])
            conn.execute("COMMIT")
        out.append(t)
    return out


def _snapshot(path) -> str | None:
    if not path.exists():
        return None
    snap = path.with_name(f"pre_rebuild_{stamp(utcnow())}.db")
    src = db.connect(path)
    dst = db.connect(snap)
    src.backup(dst)
    src.close(); dst.close()
    snaps = sorted(path.parent.glob("pre_rebuild_*.db"))
    for old in snaps[:-3]:
        old.unlink()
    return snap.name


def _swap_in(side, live) -> None:
    """Replace the live DB with the side build. A file rename fails on Windows
    while any process (the Flask app, an open shell) holds the live file open
    (WinError 5, found on the first Windows run), so the pages are copied in with
    SQLite's backup API instead: one locked, atomic write that open readers survive."""
    if not live.exists():
        os.replace(side, live)
        return
    src, dst = db.connect(side), db.connect(live)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    side.unlink()


def build(target) -> tuple[bool, list[str], str]:
    """Build a fresh DB at `target` from raw only. -> (ok, report lines, content hash)"""
    if target.exists():
        target.unlink()
    conn = db.connect(target)
    report = [f"schema: {', '.join(db.apply_schema(conn))}"]
    fw.index_raw(conn, raw.records())
    ok = True
    for lid in registry.owners("loader"):
        ld = get(lid)
        n_ok, fails, no_raw = 0, [], 0
        for sc in fw.scopes(conn, ld):
            if fw.raw_for(ld, sc) is None:
                no_raw += 1  # never fetched: nothing to replay (reported, not an error)
                continue
            res = fw.load(conn, ld, sc, apply=True)
            if res["failures"]:
                fails.append(f"{sc.label}: {'; '.join(res['failures'])}")
            else:
                n_ok += 1
        report.append(f"{lid}: {n_ok} scopes loaded" + (f", {no_raw} with no raw file" if no_raw else "")
                      + (f", {len(fails)} FAILED" if fails else ""))
        report.extend("  " + f for f in fails[:10])
        ok = ok and not fails
    for bid in registry.owners("builder"):
        res = BUILDERS[bid](conn)
        report.append(f"{bid}: {res.get('summary', '')}" + (f" FAILED {res['failures']}" if res["failures"] else ""))
        ok = ok and not res["failures"]
    h = db.content_hash(conn)
    conn.close()
    return ok, report, h


def run() -> int:
    http.NETWORK_ENABLED = False
    live = config.DB_PATH
    side = live.with_name(live.stem + ".rebuild.db")
    exported = []
    if live.exists():
        c = db.connect(live)
        exported = export_app_state(c)
        c.close()
    ok, report, h = build(side)
    print("\n".join(report))
    if not ok:
        print(f"REBUILD FAILED; live database left untouched. Side build kept at {side.name} for inspection.")
        return 1
    conn = db.connect(side)
    imported = import_app_state(conn)
    h = db.content_hash(conn)
    conn.close()
    snap = _snapshot(live)
    _swap_in(side, live)
    print(f"app state exported {exported or 'none'}, imported {imported or 'none'}; snapshot {snap or 'none (no prior DB)'}")
    print(f"network calls during rebuild: {http.CALLS}")
    print(f"content hash: {h}")
    return 0
