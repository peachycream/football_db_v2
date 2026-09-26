"""`fdb weekly`: the scheduled job (REBUILD_DESIGN §7).

Status is written as 'running' BEFORE any work, so a killed run leaves evidence:
the next run finds a stale 'running' and reports it. (v1's 09-22 job was killed
mid-load and left no trace at all.)"""
import json
import time
import traceback

from . import alert, config, db, loader as fw, registry, schedule
from .loaders import get
from .timeutil import parse_utc, utcnow


def _read_status() -> dict:
    try:
        return json.loads(config.STATUS_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _write_status(st: dict) -> None:
    tmp = config.STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    tmp.replace(config.STATUS_PATH)


def run_loader(conn, lid: str) -> dict:
    ld = get(lid)
    t0 = time.time()
    detail = {"loader": lid, "fetched": 0, "cached": 0, "loaded": 0, "failures": []}
    if ld.grain == "reference":
        target = [fw.Scope(0)]
    else:
        season = schedule.current_season(conn)
        target = fw.scopes(conn, ld, [season]) if season else []
    for part in sorted({ld.partition(s) for s in target}):
        _, fetched = fw.fetch(conn, ld, part)
        detail["fetched" if fetched else "cached"] += 1
    for sc in fw.scopes(conn, ld, None if ld.grain == "reference" else [schedule.current_season(conn)]):
        res = fw.load(conn, ld, sc, apply=True)
        if res["failures"]:
            detail["failures"].append(f"{sc.label}: " + "; ".join(res["failures"]))
        else:
            detail["loaded"] += 1
        if res["new_fields"]:
            detail.setdefault("warnings", []).append(f"new source fields: {res['new_fields']}")
    detail["rc"] = 1 if detail["failures"] else 0
    detail["duration_s"] = round(time.time() - t0, 1)
    return detail


def run() -> int:
    now = utcnow()
    prev = _read_status()
    notes = []
    if prev.get("state") == "running":
        age_h = (now - parse_utc(prev["started_at"])).total_seconds() / 3600
        if age_h > config.STALE_RUN_HOURS:
            notes.append(f"PREVIOUS RUN DID NOT FINISH (started {prev['started_at']}, never completed).")
        else:
            print(f"another run started {age_h:.1f}h ago and is still marked running; exiting")
            return 2
    st = {"state": "running", "started_at": now.isoformat(), "steps": [], "notes": notes}
    _write_status(st)

    conn = db.connect()
    db.apply_schema(conn)
    rc = 0
    for lid in registry.weekly_loaders():
        try:
            step = run_loader(conn, lid)
        except Exception as e:
            step = {"loader": lid, "rc": 1, "failures": [f"{type(e).__name__}: {e}"],
                    "trace": traceback.format_exc()[-1500:]}
        st["steps"].append(step)
        _write_status(st)
        rc = rc or step["rc"]

    season = schedule.current_season(conn)
    st.update(state="failed" if rc else "ok", finished_at=utcnow().isoformat(),
              current_season=season,
              completed_weeks=[f"{t}{w}" for t, w in schedule.completed_weeks(conn, season)] if season else [],
              content_hash=db.content_hash(conn))
    _write_status(st)

    lines = [f"football_db_v2 weekly: {'FAILED' if rc else 'OK'} ({len(st['steps'])} steps)"] + notes
    for s in st["steps"]:
        mark = "FAIL" if s["rc"] else "ok"
        lines.append(f"- {s['loader']}: {mark}" + (f" - {s['failures'][0][:300]}" if s.get("failures") else ""))
    print("\n".join(lines))
    alert.send("\n".join(lines))
    return rc


def test_alert() -> int:
    """Runs no loaders and touches no database: an alert nobody has seen work is not an alert."""
    ok = alert.send("football_db_v2: test alert (no loaders were run).")
    print("test alert sent" if ok else "test alert NOT sent (see above)")
    return 0 if ok else 1
