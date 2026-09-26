"""python -m fdb <command>. Dry-run by default for anything that writes core tables."""
import argparse
import json
import sys

from . import db, loader as fw, rebuild, schedule, weekly
from .loaders import LOADERS, get


def _conn():
    c = db.connect()
    db.apply_schema(c)
    return c


def cmd_fetch(a):
    conn, ld = _conn(), get(a.loader)
    parts = ["all"] if ld.grain in ("reference", "snapshot") else sorted({ld.partition(s) for s in fw.scopes(conn, ld, a.season)})
    for p in parts:
        rec, fetched = fw.fetch(conn, ld, p, refetch=a.refetch)
        print(f"{'fetched' if fetched else 'cached '} {rec.path} rows={rec.row_count} final={rec.is_final}")
    return 0


def cmd_load(a):
    conn, ld = _conn(), get(a.loader)
    rc = 0
    for sc in fw.scopes(conn, ld, a.season):
        res = fw.load(conn, ld, sc, apply=a.apply)
        state = "APPLIED" if res["applied"] else ("FAILED" if res["failures"] else "dry-run ok")
        print(f"{sc.label}: {state} rows={res['rows']}" + (f"  {res['failures']}" if res["failures"] else ""))
        if res["new_fields"]:
            print(f"  warning: new source fields {res['new_fields']}")
        rc = rc or bool(res["failures"])
    if not a.apply:
        print("(dry run: nothing written; pass --apply)")
    return rc


def cmd_update(a):
    return cmd_fetch(a) or cmd_load(a)


def cmd_weeks(a):
    conn = _conn()
    season = a.season or schedule.current_season(conn)
    wk = schedule.completed_weeks(conn, season)
    print(json.dumps({"season": season, "closed": schedule.season_is_closed(conn, season),
                      "completed_weeks": [f"{t} {w}" for t, w in wk]}, indent=2))
    return 0


def cmd_check(a):
    conn, rc = _conn(), 0
    for lid in (a.loader or sorted(LOADERS)):
        ld = get(lid)
        sc = fw.scopes(conn, ld)
        if not sc:
            print(f"{lid}: no scopes loaded"); continue
        ok, before, after = fw.check_idempotent(conn, ld, sc[-1])
        print(f"{lid} {sc[-1].label}: {'IDEMPOTENT' if ok else 'CHANGED ON RE-RUN'}")
        rc = rc or not ok
    return rc


def cmd_identity(a):
    from . import identity
    r = identity.build(_conn(), apply=a.apply)
    print(json.dumps(r, indent=2))
    if not a.apply:
        print("(dry run: nothing written; pass --apply)")
    return 1 if r["failures"] else 0


def cmd_reconcile(a):
    from . import reconcile
    conn, rc = _conn(), 0
    for season in a.season:
        for name, val, ok in reconcile.run(conn, season):
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {val}")
            rc = rc or not ok
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(prog="fdb")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, h in (("fetch", cmd_fetch, "fetch raw for a loader"),
                        ("load", cmd_load, "load core rows from raw (dry-run unless --apply)"),
                        ("update", cmd_update, "fetch then load")):
        s = sub.add_parser(name, help=h)
        s.add_argument("loader")
        s.add_argument("--season", type=int, nargs="*", help="narrow the framework's scopes to these seasons")
        s.add_argument("--apply", action="store_true")
        s.add_argument("--refetch", action="store_true", help="ignore a usable cached raw file")
        s.set_defaults(fn=fn)
    s = sub.add_parser("identity", help="rebuild players / player_ids / identity_quarantine")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_identity)
    s = sub.add_parser("reconcile", help="cross-source agreement checks")
    s.add_argument("--season", type=int, nargs="+", required=True)
    s.set_defaults(fn=cmd_reconcile)
    s = sub.add_parser("weeks", help="completed weeks per the schedule")
    s.add_argument("--season", type=int)
    s.set_defaults(fn=cmd_weeks)
    s = sub.add_parser("check", help="idempotency: reload the latest scope and compare hashes")
    s.add_argument("--loader", nargs="*")
    s.set_defaults(fn=cmd_check)
    sub.add_parser("rebuild", help="rebuild the DB from data/raw with the network disabled").set_defaults(fn=lambda a: rebuild.run())
    s = sub.add_parser("weekly", help="the scheduled job")
    s.add_argument("--test-alert", action="store_true")
    s.set_defaults(fn=lambda a: weekly.test_alert() if a.test_alert else weekly.run())
    sub.add_parser("hash", help="content hash of the database").set_defaults(
        fn=lambda a: print(db.content_hash(_conn())) or 0)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
