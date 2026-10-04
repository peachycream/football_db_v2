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
    rc = 0
    for p in fw.fetch_partitions(conn, ld, a.season):
        try:
            rec, fetched = fw.fetch(conn, ld, p, refetch=a.refetch)
        except Exception as e:  # one refused partition (MFL 429) must not hide the others
            print(f"FAILED  {ld.source}/{ld.endpoint}/{p}: {type(e).__name__}: {e}")
            rc = 1
            continue
        print(f"{'fetched' if fetched else 'cached '} {rec.path} rows={rec.row_count} final={rec.is_final}")
    return rc


def cmd_load(a):
    conn, ld = _conn(), get(a.loader)
    rc = 0
    for sc in fw.scopes(conn, ld, a.season):
        if fw.raw_for(ld, sc) is None:
            print(f"{sc.label}: no raw file (not fetched yet)")
            rc = 1
            continue
        res = fw.load(conn, ld, sc, apply=a.apply)
        state = "APPLIED" if res["applied"] else ("FAILED" if res["failures"] else "dry-run ok")
        print(f"{sc.label}: {state} rows={res['rows']}" + (f"  {res['failures']}" if res["failures"] else ""))
        if res["new_fields"]:
            print(f"  warning: new source fields {res['new_fields']}")
        rc = rc or bool(res["failures"])
    if a.apply and fw.sync_snapshots(conn, ld):
        print("removed core rows of snapshots whose raw file was pruned")
    if not a.apply:
        print("(dry run: nothing written; pass --apply)")
    return rc


def cmd_update(a):
    rc = cmd_fetch(a)
    return cmd_load(a) or rc  # load whatever was fetched, even if some partitions were refused


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


def cmd_card(a):
    from . import card_render
    conn = _conn()
    try:
        path, card = card_render.render_to_file(conn, a.league, a.season, a.week, a.home, a.away, a.out)
    except card_render.RenderError as e:
        print(f"card: {e}")
        return 1
    finally:
        conn.close()
    pk = card["pick"] or {}
    print(f"{path}  ({card['away']['name']} at {card['home']['name']}, {card['league_name']} {card['season']} week {card['week']}, "
          f"{card['state']}{', FEATURED' if card['featured'] else ''}; ranked on {pk.get('basis')})")
    print("rendered only; nothing was posted")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["parity-ownership"]:  # its own parser: argparse REMAINDER drops leading --options
        from . import parity
        return parity.main(argv[1:])
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
    s = sub.add_parser("card", help="render the Matchup of the Week card to a PNG (data/cards/); posts nothing")
    s.add_argument("--league")
    s.add_argument("--season", type=int)
    s.add_argument("--week", type=int)
    s.add_argument("--home")
    s.add_argument("--away")
    s.add_argument("--out", help="write here instead of data/cards/")
    s.set_defaults(fn=cmd_card)
    sub.add_parser("parity-ownership", help="Phase 3 gate: /ownership/ owners vs the v1 oracle (see fdb/parity.py)")
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
