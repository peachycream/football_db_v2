"""Phase 14: build the devy roster seed CSV and the CFBD review sheet (a PROPOSAL, not a mapping).

The screenshots carry names only, so no exact key exists yet. This tool lists, for every distinct
as-written player, the CFBD players the search returns, with the evidence a human needs (school,
position, height, weight, active years). Turon's approval of a row (column `approved_cfbd_id`) is the
exact key; nothing loads against an unapproved row. A name or position may REJECT a candidate here,
it never selects one: `proposal` is only a hint for the reviewer.

  python -m fdb.devy_candidates SEED_TXT          # writes app_state/app_devy_roster.csv + data/devy_review.csv
"""
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict

from . import config

API = "https://api.collegefootballdata.com"
SEED_COLS = ["league_id", "franchise_id", "franchise_name", "line", "devy_slot", "source_text", "position",
             "school_text", "seen_on"]
SEEN_ON = {"57653": "2026-08-31", "60398": "2026-08-08", "60856": "2026-09-09", "55757": "2026-09-01"}
GROUP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "WR/TE": "WR", "DE": "DL", "DT": "DL", "EDGE": "DL",
         "DL": "DL", "LB": "LB", "DB": "DB", "CB": "DB", "S": "DB"}


def read_seed(path: str) -> list[dict]:
    rows, last = [], {}
    for raw in open(path, encoding="utf-8"):
        raw = raw.rstrip("\n")
        if not raw.strip():
            continue
        lg, fid, fname, slot, name, pos, school = raw.split("|")
        key = (lg, fid)
        slot = int(slot)
        # a new line of the same franchise starts when the column number stops increasing
        line = last.get(key, (1, 0))
        line = (line[0] + 1, slot) if slot <= line[1] else (line[0], slot)
        last[key] = line
        rows.append({"league_id": lg, "franchise_id": fid, "franchise_name": fname, "line": line[0],
                     "devy_slot": slot, "source_text": name, "position": pos, "school_text": school,
                     "seen_on": SEEN_ON[lg]})
    return rows


def _get(path: str, key: str):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main(seed_txt: str):
    key = config.env("CFB_API_KEY")
    if not key:
        raise SystemExit("CFB_API_KEY missing")
    rows = read_seed(seed_txt)
    with open(config.APP_STATE_DIR / "app_devy_roster.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SEED_COLS)
        w.writeheader()
        w.writerows(rows)
    players = OrderedDict()
    for r in rows:
        players.setdefault((r["source_text"], r["position"], r["school_text"]), []).append(f"{r['league_id']}/{r['franchise_id']}")
    out = []
    for (name, pos, school), where in players.items():
        q = urllib.parse.quote(name.replace('"', "").strip())
        try:
            cands = _get(f"/player/search?searchTerm={q}", key)
        except Exception as e:  # a failed search is reported, not hidden
            cands = []
            err = str(e)[:80]
        else:
            err = ""
        time.sleep(0.15)
        g = GROUP.get(pos.upper().strip())
        kept = []
        for c in cands:
            cg = GROUP.get((c.get("position") or "").upper())
            if g and cg and g != cg:      # position may REJECT a candidate
                continue
            if (c.get("activeEndYear") or 0) < 2025:   # not an active/recent college player
                continue
            kept.append(c)
        proposal = kept[0]["id"] if len(kept) == 1 else ""
        out.append({
            "source_text": name, "position": pos, "school_text": school, "n_rows": len(where),
            "candidates": len(kept), "proposal_cfbd_id": proposal,
            "cand_detail": " || ".join(f"{c['id']}:{c.get('name')}, {c.get('position')}, {c.get('team')}, "
                                       f"{c.get('height')}in/{c.get('weight')}lb, {c.get('activeStartYear')}-{c.get('activeEndYear')}"
                                       for c in kept),
            "search_error": err, "approved_cfbd_id": "", "reason": "",
        })
    with open(config.ROOT / "data" / "devy_review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    n1 = sum(1 for o in out if o["candidates"] == 1)
    print(f"seed rows {len(rows)}; distinct players {len(out)}; one candidate {n1}; "
          f"several {sum(1 for o in out if o['candidates'] > 1)}; none {sum(1 for o in out if o['candidates'] == 0)}")


if __name__ == "__main__":
    main(sys.argv[1])
