"""One-time import of v1's draft wishlist into app_wishlist / app_wishlist_priority
(Phase 3). The ONLY data v2 ever copies from v1: it is user-entered, so no source
can regenerate it.

v1 keyed the wishlist on name slugs ('combs_branson'). Each slug is re-keyed to a
gsis_id by EXACT keys only, never by name:
  * v1 players.gsis_id                 (v1's own column; v1 mis-stamped 5,233 of them,
                                        so it is never trusted alone)
  * v1 player_source_ids sleeper/mfl   -> v2 player_ids (source, source_id)
A slug is imported when at least one key resolves through v2's player_ids and every
key that resolves agrees - or, with no v2-resolved key, when v1's gsis_id is known to
v2 AND v1's birth date equals v2's exactly (one exact key + an independent
biographical fact: the same bar as the Sleeper cross-id bridge in identity.py).
Anything else is listed with its reason, never guessed.
v1 is opened read-only (mode=ro).

    python -m fdb.wishlist_import --v1 <path to v1 football.db> [--apply]
"""
import argparse
import sqlite3
import sys

from . import db
from .names import name_disagrees


def plan(v1: sqlite3.Connection, v2: sqlite3.Connection) -> tuple[list[dict], list[dict], list[dict]]:
    """-> (wishlist rows, priority rows, unmapped [{slug, reason}])."""
    v1.row_factory = sqlite3.Row
    rows, unmapped, slug_gsis = [], [], {}
    for w in v1.execute("SELECT w.*, p.full_name, p.birth_date AS v1_birth, p.gsis_id AS v1_gsis FROM draft_wishlist w "
                        "LEFT JOIN players p ON p.player_id = w.player_id ORDER BY w.player_id"):
        slug = w["player_id"]
        keys = {}
        for src, sid in v1.execute("SELECT source, source_player_id FROM player_source_ids "
                                   "WHERE player_id = ? AND source IN ('sleeper', 'mfl')", (slug,)):
            hit = v2.execute("SELECT gsis_id FROM player_ids WHERE source = ? AND source_id = ?", (src, sid)).fetchone()
            keys[f"{src}:{sid}"] = hit[0] if hit else None
        via_v2 = {k: g for k, g in keys.items() if g}
        v1_gsis = w["v1_gsis"]
        if v1_gsis and not v2.execute("SELECT 1 FROM players WHERE gsis_id = ?", (v1_gsis,)).fetchone():
            v1_gsis = None  # a v1 gsis v2 does not know cannot be a key
        cands = set(via_v2.values()) | ({v1_gsis} if v1_gsis else set())
        if not via_v2 and v1_gsis and w["v1_birth"] and v2.execute(
                "SELECT birth_date FROM players WHERE gsis_id = ?", (v1_gsis,)).fetchone()[0] == w["v1_birth"]:
            via_v2 = {"v1 gsis + exact birth date": v1_gsis}
        if not via_v2:
            unmapped.append({"slug": slug, "reason": f"no v1 sleeper/mfl id resolves in v2 player_ids (keys {keys}, v1 gsis {w['v1_gsis']})"})
            continue
        if len(cands) > 1:
            unmapped.append({"slug": slug, "reason": f"exact keys disagree: {via_v2}, v1 gsis {w['v1_gsis']}"})
            continue
        g = cands.pop()
        person = dict(v2.execute("SELECT display_name, first_name, last_name, birth_date FROM players WHERE gsis_id = ?",
                                 (g,)).fetchone())
        if name_disagrees(w["full_name"] or "", person):  # a name may reject, never select
            unmapped.append({"slug": slug, "reason": f"v1 name {w['full_name']!r} disagrees with {person['display_name']!r} ({g})"})
            continue
        slug_gsis[slug] = g
        rows.append({"gsis_id": g, "source_context": w["source_context"], "note": w["note"], "priority": w["priority"],
                     "created_at": w["created_at"], "_slug": slug, "_keys": sorted(via_v2) + (["v1 gsis"] if v1_gsis and "v1 gsis + exact birth date" not in via_v2 else []),
                     "_name": person["display_name"]})
    prio = []
    for p in v1.execute("SELECT player_id, league_id, priority, updated_at FROM draft_wishlist_priority ORDER BY 1, 2"):
        if p["player_id"] not in slug_gsis:
            unmapped.append({"slug": p["player_id"], "reason": f"league priority for an unmapped slug ({p['league_id']})"})
            continue
        parts = p["league_id"].split(":")  # v1 'mfl:30590:2026' -> v2 'mfl:30590'
        prio.append({"gsis_id": slug_gsis[p["player_id"]], "league_key": ":".join(parts[:2]),
                     "priority": p["priority"], "updated_at": p["updated_at"]})
    return rows, prio, unmapped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fdb.wishlist_import")
    ap.add_argument("--v1", required=True, help="path to the v1 football.db (opened read-only)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    v1 = sqlite3.connect(f"file:{a.v1}?mode=ro", uri=True)
    v2 = db.connect()
    db.apply_schema(v2)
    rows, prio, unmapped = plan(v1, v2)
    for r in rows:
        print(f"map    {r['_slug']:<22} -> {r['gsis_id']} {r['_name']:<22} via {', '.join(r['_keys'])}")
    for u in unmapped:
        print(f"UNMAPPED {u['slug']}: {u['reason']}")
    print(f"{len(rows)} wishlist rows, {len(prio)} league priorities, {len(unmapped)} unmapped")
    if not a.apply:
        print("(dry run: nothing written; pass --apply)")
        return 1 if unmapped else 0
    if v2.execute("SELECT COUNT(*) FROM app_wishlist").fetchone()[0]:
        print("app_wishlist is not empty; the import runs once, into an empty table. Nothing written.")
        return 1
    v2.execute("BEGIN")
    v2.executemany("INSERT INTO app_wishlist (gsis_id, source_context, note, priority, created_at) VALUES (?,?,?,?,?)",
                   [(r["gsis_id"], r["source_context"], r["note"], r["priority"], r["created_at"]) for r in rows])
    v2.executemany("INSERT INTO app_wishlist_priority (gsis_id, league_key, priority, updated_at) VALUES (?,?,?,?)",
                   [(p["gsis_id"], p["league_key"], p["priority"], p["updated_at"]) for p in prio])
    v2.execute("COMMIT")
    from .rebuild import export_app_state
    print(f"imported; exported {export_app_state(v2)} to app_state/")
    return 1 if unmapped else 0


if __name__ == "__main__":
    sys.exit(main())
