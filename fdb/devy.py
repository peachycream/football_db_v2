"""Phase 14 builder `devy.identity`: config/devy_identity.csv -> devy_identity, and the checks that make it safe.

The CSV is Turon's approved review sheet (data/devy_review.csv, drafted by fdb/devy_candidates.py). A row maps
the AS-WRITTEN screenshot cell (text, position, school) to a CFBD id. Nothing here looks a player up by name:
the key is the cell, the value is what Turon approved. A blank cfbd_id is a deliberate skip (with a reason).
"""
import csv

from . import config

PATH = config.ROOT / "config" / "devy_identity.csv"
PFF_PATH = config.ROOT / "config" / "devy_pff_identity.csv"


def build(conn) -> dict:
    with open(PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fails = []
    seen, uniq = {}, []
    for r in rows:
        k = (r["source_text"], r["position"], r["school_text"])
        if k in seen:
            if seen[k] != r["cfbd_id"]:   # the same cell approved as two different players
                fails.append(f"{k}: approved as {seen[k] or 'skip'} and {r['cfbd_id'] or 'skip'}")
            continue
        seen[k] = r["cfbd_id"]
        uniq.append(r)
    rows = uniq
    for r in rows:
        if not r["cfbd_id"] and not r["reason"]:
            fails.append(f"{r['source_text']} [{r['school_text']}]: neither an id nor a reason for skipping")
    if fails:
        return {"failures": fails, "summary": "identity CSV refused"}
    conn.execute("BEGIN")
    conn.execute("DELETE FROM devy_identity")
    conn.executemany("INSERT INTO devy_identity (source_text, position, school_text, cfbd_id, reason) VALUES (?,?,?,?,?)",
                     [(r["source_text"], r["position"], r["school_text"], r["cfbd_id"] or None, r["reason"] or None)
                      for r in rows])
    # every screenshot cell has an approved row, and no row is orphaned
    unmapped = conn.execute("""SELECT DISTINCT d.source_text, d.position, d.school_text FROM app_devy_roster d
        LEFT JOIN devy_identity i ON i.source_text = d.source_text AND i.position = d.position AND i.school_text = d.school_text
        WHERE i.source_text IS NULL""").fetchall()
    if unmapped:
        fails.append(f"{len(unmapped)} roster cells with no approved identity row, e.g. {[tuple(u) for u in unmapped[:3]]}")
    # an approved id must exist in CFBD's own data (loaded seasons); a stale id fails loudly
    have = {r[0] for r in conn.execute("SELECT DISTINCT id FROM core_cfbd_roster UNION SELECT DISTINCT playerId FROM core_cfbd_player_season")}
    if have:
        missing = sorted({r["cfbd_id"] for r in rows if r["cfbd_id"]} - have)
        if missing:
            fails.append(f"approved CFBD ids not found in the loaded CFBD seasons: {missing}")
    with open(PFF_PATH, encoding="utf-8-sig") as f:
        pff = list(csv.DictReader(f))
    ids = [r["cfbd_id"] for r in pff]
    if len(set(ids)) != len(ids):
        fails.append("config/devy_pff_identity.csv: a CFBD id appears twice")
    known = {r["cfbd_id"] for r in rows if r["cfbd_id"]}
    stray = sorted(set(ids) - known)
    if stray:
        fails.append(f"devy_pff_identity names CFBD ids that are not in devy_identity: {stray[:5]}")
    pff_have = set()
    for f in ("passing", "rushing", "receiving", "defense", "pass_rush"):
        pff_have |= {str(x[0]) for x in conn.execute(f"SELECT DISTINCT player_id FROM core_pff_ncaa_{f}_season")}
    if pff_have:
        gone = sorted(r["pff_id"] for r in pff if r["pff_id"] and r["pff_id"] not in pff_have)
        if gone:
            fails.append(f"approved PFF ids not found in the loaded PFF college seasons: {gone[:5]}")
    conn.execute("DELETE FROM devy_pff_identity")
    conn.executemany("INSERT INTO devy_pff_identity (cfbd_id, pff_id, reason) VALUES (?,?,?)",
                     [(r["cfbd_id"], int(r["pff_id"]) if r["pff_id"] else None, r["reason"] or None) for r in pff])
    if fails:
        conn.execute("ROLLBACK")
    else:
        conn.execute("COMMIT")
    return {"failures": fails, "summary": f"{len(rows)} identity rows, {sum(1 for r in rows if r['cfbd_id'])} mapped, "
                                          f"{sum(1 for r in pff if r['pff_id'])} PFF links"}
