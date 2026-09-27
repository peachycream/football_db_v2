"""Phase 3 gate: /ownership/ answers vs the v1 oracle (read-only).

For a deterministic sample of players, compare the OWNER FRANCHISES per league
(and pool) that v2's mart_roster_ownership gives with what v1's fantasy_rosters
gives. v1 is opened with mode=ro and is never a data source for v2.

Player matching v2 -> v1 is by exact keys only: v1 player_source_ids (mfl, sleeper)
and v1 players.gsis_id. A v2 player whose keys point at two v1 slugs (or none) is
reported as such - that is a v1 identity finding, not something to resolve here.

    python -m fdb parity-ownership --v1 <v1 football.db> [--n 50] [--seed 3]
"""
import json
import random
import sqlite3
from collections import defaultdict

V1_SEASON = 2026


def _v1_slugs(v1, v2, key):
    """v2 player_key -> {v1 slug: [evidence]} via exact keys."""
    out = defaultdict(list)
    if key.startswith("mfl:"):
        _, league, sid = key.split(":")
        # league-scoped devy id: v1 keyed those by name slug; only its mfl source id can match
        for (slug,) in v1.execute("SELECT player_id FROM player_source_ids WHERE source = 'mfl' AND source_player_id = ?", (sid,)):
            out[slug].append(f"v1 mfl:{sid}")
        return out
    if key.startswith("sleeper:"):
        sid = key.split(":")[1]
        for (slug,) in v1.execute("SELECT player_id FROM player_source_ids WHERE source = 'sleeper' AND source_player_id = ?", (sid,)):
            out[slug].append(f"v1 sleeper:{sid}")
        return out
    for src, sid in v2.execute("SELECT source, source_id FROM player_ids WHERE gsis_id = ? AND source IN ('mfl', 'sleeper')", (key,)):
        for (slug,) in v1.execute("SELECT player_id FROM player_source_ids WHERE source = ? AND source_player_id = ?", (src, sid)):
            out[slug].append(f"{src}:{sid}")
    for (slug,) in v1.execute("SELECT player_id FROM players WHERE gsis_id = ?", (key,)):
        out[slug].append("v1 gsis")
    return out


def _v2_owners(v2, key, season):
    """-> {(platform, league_id): {franchise: pool}}; franchise = MFL franchise id or
    Sleeper roster_id."""
    out = defaultdict(dict)
    for r in v2.execute("""SELECT platform, league_id, franchise_id, pool_name FROM mart_roster_ownership
                           WHERE season = ? AND player_key = ?""", (season, key)):
        out[(r["platform"], r["league_id"])][r["franchise_id"]] = r["pool_name"] or ""
    return out


def sleeper_team_map(v1, v2, season):
    """v1 stored a Sleeper team as its owner's display name, not its roster_id, and a
    roster can change hands (BigEWolf's roster 10 is EricKiesel's in 2026). Map each v1
    team to the v2 roster holding most of its players, by exact sleeper ids.
    -> {(league_id, v1 team): (roster_id, v2 owner, overlap, v1 size)}"""
    out = {}
    for (league_id,) in v2.execute("SELECT DISTINCT league_id FROM mart_roster_ownership WHERE platform = 'sleeper' AND season = ?", (season,)):
        v2r, owner = defaultdict(set), {}
        for fr, own, pid in v2.execute("""SELECT franchise_id, owner_name, source_player_id FROM mart_roster_ownership
                                          WHERE platform = 'sleeper' AND league_id = ? AND season = ?""", (league_id, season)):
            v2r[fr].add(pid)
            owner[fr] = own
        v1t = defaultdict(set)
        for team, slug in v1.execute("SELECT team_name, player_id FROM fantasy_rosters WHERE season = ? AND league_id = ?",
                                     (V1_SEASON, f"sleeper:{league_id}")):
            for (sid,) in v1.execute("SELECT source_player_id FROM player_source_ids WHERE source = 'sleeper' AND player_id = ?", (slug,)):
                v1t[team].add(sid)
        for team, ids in v1t.items():
            rid, have = max(v2r.items(), key=lambda kv: len(kv[1] & ids))
            out[(league_id, team)] = (rid, owner[rid], len(have & ids), len(ids))
    return out


def _v1_owners(v1, slugs, league_ids, team_map):
    out = defaultdict(set)
    for slug in slugs:
        for lid, team in v1.execute("SELECT league_id, team_name FROM fantasy_rosters WHERE season = ? AND player_id = ?",
                                    (V1_SEASON, slug)):
            parts = lid.split(":")
            k = (parts[0], parts[1])
            if k in league_ids:
                out[k].add(team_map[(parts[1], team)][0] if parts[0] == "sleeper" else team)
    return out


def sample(v2, n, seed):
    """Deterministic, stratified: players rostered in MFL only, in Sleeper, on my
    teams, devy, in multi-pool leagues, plus unrostered-in-some-league players."""
    season = v2.execute("SELECT MAX(season) FROM mart_roster_ownership").fetchone()[0]
    keys = [r[0] for r in v2.execute("SELECT DISTINCT player_key FROM mart_roster_ownership WHERE season = ? ORDER BY 1", (season,))]
    rng = random.Random(seed)
    strata = {
        "mine": [r[0] for r in v2.execute("SELECT DISTINCT player_key FROM mart_roster_ownership WHERE season = ? AND is_mine = 1 ORDER BY 1", (season,))],
        "sleeper": [r[0] for r in v2.execute("SELECT DISTINCT player_key FROM mart_roster_ownership WHERE season = ? AND platform = 'sleeper' ORDER BY 1", (season,))],
        "multi_pool": [r[0] for r in v2.execute("""SELECT DISTINCT player_key FROM mart_roster_ownership WHERE season = ?
                                                   AND pool_unit != 'LEAGUE' ORDER BY 1""", (season,))],
        "any": keys,
    }
    # Devy (league-scoped MFL ids) is NOT sampled: v1 has no exact key for them (0 mfl
    # source ids in 0800-0999; it stored them under name slugs), so a comparison would
    # need a name match. They are counted separately in the report instead.
    quota = {"mine": 10, "sleeper": 10, "multi_pool": 10, "any": n}
    picked = []
    for name in ("mine", "sleeper", "multi_pool", "any"):
        pool = [k for k in strata[name] if k not in picked and not k.startswith("mfl:")]
        rng.shuffle(pool)
        picked += pool[:min(quota[name], n - len(picked))]
    return season, picked[:n]


def run(v1_path, v2, n=50, seed=3):
    v1 = sqlite3.connect(f"file:{v1_path}?mode=ro", uri=True)
    v2.row_factory = sqlite3.Row
    season, keys = sample(v2, n, seed)
    leagues = {(r[0], r[1]) for r in v2.execute("SELECT DISTINCT platform, league_id FROM mart_roster_ownership WHERE season = ?", (season,))}
    v1_snap = dict(v1.execute("SELECT league_id, MAX(created_at) FROM fantasy_rosters WHERE season = ? GROUP BY league_id", (V1_SEASON,)).fetchall())
    tmap = sleeper_team_map(v1, v2, season)
    report = {"season": season, "v1_snapshots": v1_snap, "players": [],
              "sleeper_team_map": {f"{k[0]}:{k[1]}": v for k, v in sorted(tmap.items())}}
    for key in keys:
        slugs = _v1_slugs(v1, v2, key)
        name = v2.execute("SELECT name FROM mart_player_search WHERE player_key = ?", (key,)).fetchone()
        entry = {"key": key, "name": name[0] if name else None, "v1_slugs": dict(slugs), "leagues": []}
        v2o = _v2_owners(v2, key, season)
        v1o = _v1_owners(v1, list(slugs), leagues, tmap)
        for lg in sorted(leagues):
            a, b = set(v2o.get(lg, {})), v1o.get(lg, set())
            entry["leagues"].append({"league": f"{lg[0]}:{lg[1]}", "v2": sorted(a), "v1": sorted(b), "match": a == b,
                                     "v2_pools": v2o.get(lg, {})})
        report["players"].append(entry)
    return report


# ------------------------------------------------------------ evidence ----
# Transactions explain an ownership difference mechanically: v1's snapshot is older
# than v2's, so an owner v2 has and v1 lacks must have ADDED the player after v1's
# snapshot (and vice versa). Transactions are fetched through the raw store
# (endpoint 'transactions'); they are parity evidence only, not loaded into core.
def fetch_evidence(season: int) -> dict:
    from . import http, leagues, mfl, raw
    out = {}
    for lg in leagues.load():
        if season not in lg.seasons:
            continue
        if lg.platform == "mfl":
            body, params = mfl.export(season, lg.league_id, "transactions")
            n = len(mfl.as_list(json.loads(body)["transactions"].get("transaction")))
            paths = [raw.write("mfl", "transactions", f"{season}/{lg.league_id}", body, "json", params, n, False).path]
            # Draft picks are not transactions; a draft can straddle v1's snapshot (60398: 08-01..08-19).
            body, params = mfl.export(season, lg.league_id, "draftResults")
            units = mfl.as_list((json.loads(body).get("draftResults") or {}).get("draftUnit"))
            n = sum(len(mfl.as_list(u.get("draftPick"))) for u in units)
            paths.append(raw.write("mfl", "draftResults", f"{season}/{lg.league_id}", body, "json", params, n, False).path)
            out[("mfl", lg.league_id)] = paths
        else:
            paths = []
            for rnd in range(1, 19):
                url = f"https://api.sleeper.app/v1/league/{lg.league_id}/transactions/{rnd}"
                body = http.get(url)
                n = len(json.loads(body) or [])
                if not n:
                    break
                paths.append(raw.write("sleeper", "transactions", f"{season}/{lg.league_id}/r{rnd:02d}", body, "json",
                                       {"url": url}, n, False).path)
            out[("sleeper", lg.league_id)] = paths
    return out


def _ids(s):
    return [x for x in (s or "").split(",") if x and not x.startswith(("FP_", "DP_"))]


def events(evidence: dict) -> dict:
    """-> {(platform, league_id): [(ts_utc_seconds, franchise, player_id, 'add'|'drop', type)]}"""
    from . import config, mfl
    out = defaultdict(list)
    for (platform, league), paths in evidence.items():
        for path in paths:
            data = json.loads((config.RAW_DIR / path).read_bytes())
            if platform == "mfl" and "draftResults" in data:
                for u in mfl.as_list(data["draftResults"].get("draftUnit")):
                    for pk in mfl.as_list(u.get("draftPick")):
                        if pk.get("player") and pk.get("timestamp"):
                            out[(platform, league)].append((int(pk["timestamp"]), pk["franchise"], pk["player"], "add", "DRAFT"))
            elif platform == "mfl":
                for t in mfl.as_list(data["transactions"].get("transaction")):
                    ts, fr, typ = int(t["timestamp"]), t.get("franchise"), t["type"]
                    if typ in ("FREE_AGENT", "WAIVER", "BBID_WAIVER"):
                        parts = t.get("transaction", "").split("|")   # added,|dropped,  /  added,|bid|dropped,
                        for pid in _ids(parts[0]):
                            out[(platform, league)].append((ts, fr, pid, "add", typ))
                        for pid in _ids(parts[-1] if len(parts) > 1 else ""):
                            out[(platform, league)].append((ts, fr, pid, "drop", typ))
                    elif typ == "TRADE":
                        f2 = t.get("franchise2")
                        for pid in _ids(t.get("franchise1_gave_up")):
                            out[(platform, league)] += [(ts, fr, pid, "drop", typ), (ts, f2, pid, "add", typ)]
                        for pid in _ids(t.get("franchise2_gave_up")):
                            out[(platform, league)] += [(ts, f2, pid, "drop", typ), (ts, fr, pid, "add", typ)]
            else:
                for t in data or []:
                    if t.get("status") != "complete":
                        continue
                    ts = int(t["status_updated"]) // 1000
                    for pid, rid in (t.get("adds") or {}).items():
                        out[(platform, league)].append((ts, str(rid), pid, "add", t["type"]))
                    for pid, rid in (t.get("drops") or {}).items():
                        out[(platform, league)].append((ts, str(rid), pid, "drop", t["type"]))
    for k in out:
        out[k].sort()
    return out


def explain(v2, report: dict, evs: dict, v1=None) -> None:
    """Annotate every differing (player, league, franchise) with the transaction after
    v1's snapshot that accounts for it, or 'UNEXPLAINED'."""
    from datetime import datetime, timezone
    snap = {}
    for lid, created in report["v1_snapshots"].items():
        p = lid.split(":")
        snap[(p[0], p[1])] = int(datetime.fromisoformat(created).replace(tzinfo=timezone.utc).timestamp())
    for p in report["players"]:
        key, sids = p["key"], {"mfl": set(), "sleeper": set()}
        if key.startswith(("mfl:", "sleeper:")):
            sids[key.split(":")[0]].add(key.split(":")[-1])
        else:
            for src, sid in v2.execute("SELECT source, source_id FROM player_ids WHERE gsis_id = ? AND source IN ('mfl','sleeper')", (key,)):
                sids[src].add(sid)
        for l in p["leagues"]:
            if l["match"]:
                continue
            platform, league = l["league"].split(":")
            since = snap.get((platform, league))
            notes = []
            for fr, want in [(f, "add") for f in sorted(set(l["v2"]) - set(l["v1"]))] + \
                            [(f, "drop") for f in sorted(set(l["v1"]) - set(l["v2"]))]:
                hits = [e for e in evs.get((platform, league), [])
                        if e[1] == fr and e[2] in sids[platform] and (since is None or e[0] > since)]
                last = hits[-1] if hits else None
                if last and last[3] == want:
                    notes.append(f"{fr}: {want} via {last[4]} {datetime.fromtimestamp(last[0], timezone.utc):%Y-%m-%d}")
                elif want == "add" and not hits:
                    # Held since before v1's snapshot (no add/drop/trade/draft after it), yet
                    # v1's snapshot lacks the slot: v1 dropped it (the own_03 class of bug).
                    notes.append(f"{fr}: V1_DROPPED_SLOT (held since before v1's snapshot; {_v1_key_note(v1, sids, platform, since)})")
                else:
                    notes.append(f"{fr}: UNEXPLAINED ({'v2 has, v1 lacks' if want == 'add' else 'v1 has, v2 lacks'})")
            l["explained"] = notes


def _v1_key_note(v1, sids, platform, since):
    if v1 is None:
        return "v1 mapping not checked"
    from datetime import datetime, timezone
    notes = []
    for sid in sorted(sids[platform]):
        rows = v1.execute("SELECT player_id, created_at FROM player_source_ids WHERE source = ? AND source_player_id = ?",
                          (platform, sid)).fetchall()
        if not rows:
            notes.append(f"v1 has no slug for {platform} id {sid}")
        for slug, created in rows:
            ts = datetime.fromisoformat(created).replace(tzinfo=timezone.utc).timestamp()
            notes.append(f"v1 mapped {platform} {sid} -> {slug} {'AFTER' if since and ts > since else 'before'} its snapshot")
    return "; ".join(notes) or "no source id"


def main(argv=None) -> int:
    import argparse
    from . import db
    ap = argparse.ArgumentParser(prog="fdb parity-ownership")
    ap.add_argument("--v1", required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("--explain", action="store_true", help="fetch league transactions (raw store) to explain differences")
    a = ap.parse_args(argv)
    v2 = db.connect()
    rep = run(a.v1, v2, a.n, a.seed)
    if a.explain:
        v1 = sqlite3.connect(f"file:{a.v1}?mode=ro", uri=True)
        explain(v2, rep, events(fetch_evidence(rep["season"])), v1)
        for k, (rid, owner, ov, n) in rep["sleeper_team_map"].items():
            if owner != k.split(":", 1)[1]:
                print(f"sleeper {k}: v1 team is roster {rid}, now owned by {owner} ({ov}/{n} of its v1 players still on it)")
    cells = [(p, l) for p in rep["players"] for l in p["leagues"]]
    bad = [(p, l) for p, l in cells if not l["match"]]
    print(f"{len(rep['players'])} players x {len(cells) // max(1, len(rep['players']))} leagues = {len(cells)} "
          f"league answers; {len(cells) - len(bad)} match v1, {len(bad)} differ")
    for p, l in bad:
        print(f"  DIFF {p['key']} {p['name']!s:<24} {l['league']:<30} v2={l['v2']} v1={l['v1']} slugs={list(p['v1_slugs'])}")
        for n in l.get("explained", []):
            print(f"         {n}")
    if a.explain:
        notes = [n for _, l in bad for n in l.get("explained", [])]
        print(f"{len(notes)} franchise-level differences: "
              f"{sum(' via ' in n for n in notes)} explained by a transaction/draft pick after v1's snapshot, "
              f"{sum('V1_DROPPED_SLOT' in n for n in notes)} are slots v1's snapshot dropped, "
              f"{sum('UNEXPLAINED' in n for n in notes)} UNEXPLAINED")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
