"""Phase 14: the PFF review sheet (a PROPOSAL, not a mapping), drafted from loaded core tables only (no network).

PFF college ids share no key with CFBD ids, so the link is, like the CFBD one, Turon's approval of a row
(`approved_pff_id`). For every approved CFBD player this lists the PFF college players whose normalised name
equals the CFBD name (punctuation and Jr/II suffixes ignored), with the evidence a reviewer needs: PFF team code,
position, games, eligible_season. A name only PROPOSES here; nothing loads against an unapproved row.

  python -m fdb.devy_pff_candidates        # writes data/devy_pff_review.csv
"""
import csv
import re

from . import config, db

FACETS = ("passing", "rushing", "receiving", "defense", "pass_rush")


def norm(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", (s or "").lower().replace("-", " "))
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def main():
    c = db.connect()
    ident = list(csv.DictReader(open(config.ROOT / "config" / "devy_identity.csv", encoding="utf-8-sig")))
    ids = sorted({r["cfbd_id"] for r in ident if r["cfbd_id"]})
    names = {}
    for sid, fn, ln, team, pos, yr in c.execute(
            "SELECT id, firstName, lastName, team, position, season FROM core_cfbd_roster ORDER BY season"):
        names[sid] = (f"{fn} {ln}", team, pos)      # the newest season wins
    pff = {}
    for f in FACETS:
        for pid, name, pos, team, games, elig, drafted, season in c.execute(
                f"SELECT player_id, player, position, team_name, player_game_count, eligible_season, draft_season, season "
                f"FROM core_pff_ncaa_{f}_season"):
            d = pff.setdefault(pid, {"name": name, "pos": set(), "team": set(), "elig": set(), "draft": set(), "seasons": set()})
            d["pos"].add(pos); d["team"].add(team); d["seasons"].add(season)
            if elig: d["elig"].add(elig)
            if drafted: d["draft"].add(drafted)
    by_name = {}
    for pid, d in pff.items():
        by_name.setdefault(norm(d["name"]), []).append(pid)
    out = []
    for cid in ids:
        nm, team, pos = names.get(cid, ("", "", ""))
        if not nm:   # not on the 2025/2026 CFBD roster: take the name from the stats table
            r = c.execute("SELECT player, team, position FROM core_cfbd_player_season WHERE playerId = ? LIMIT 1", (cid,)).fetchone()
            nm, team, pos = (r[0], r[1], r[2]) if r else ("", "", "")
        cands = by_name.get(norm(nm), [])
        out.append({
            "cfbd_id": cid, "cfbd_name": nm, "cfbd_team": team, "cfbd_position": pos,
            "candidates": len(cands), "proposal_pff_id": cands[0] if len(cands) == 1 else "",
            "cand_detail": " || ".join(
                f"{p}:{pff[p]['name']}, {'/'.join(sorted(pff[p]['pos']))}, {'/'.join(sorted(pff[p]['team']))}, "
                f"seasons {sorted(pff[p]['seasons'])}, eligible {sorted(pff[p]['elig'])}, drafted {sorted(pff[p]['draft'])}"
                for p in cands),
            "approved_pff_id": "", "reason": ""})
    with open(config.ROOT / "data" / "devy_pff_review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    print(f"{len(out)} CFBD players; one PFF candidate {sum(1 for o in out if o['candidates'] == 1)}; "
          f"several {sum(1 for o in out if o['candidates'] > 1)}; none {sum(1 for o in out if o['candidates'] == 0)}")


if __name__ == "__main__":
    main()
