"""Phase 15e-3 (PHASE15E3_SPEC.md): the CFBD bridge -> mart_idp_prospect_cfbd_bridge (builder `idp_prospect.cfbd_bridge`).

Every drafted defender 2017+ (core_nflverse_draft_picks side D, exact gsis_id) gets, where the keys allow it:
  - a CFBD athlete id: CFBD /draft/picks joined to the nflverse draft table on (season, overall pick), nothing else;
  - the pre-draft scouting ranks and grade CFBD attaches to that pick;
  - a recruit: the athlete's core_cfbd_roster rows (seasons <= draft year - 1) name recruit ids in `recruitIds`; exactly one
    distinct id that is in core_cfbd_recruiting_players gives stars, rating and rank.
A name or a college string is never read. What CAN reject a pair, and only reject it: the CFBD drafting team is not the nflverse
team (a fixed 30-name table, TEAM_CODES), a roster that names more than one recruit id, a recruit row whose own `athleteId` is
non-empty and is a different athlete. A rejected pair leaves its CFBD columns NULL and the status says why.
"""
import json

from .idp_prospect import _team_resolver

FIRST_DRAFT = 2017
GATE_LAST_DRAFT = 2025         # the bridge gate covers closed classes 2017-2025 (2026's college season is the last one loaded)
MIN_BRIDGE = 0.95              # PHASE15E3_SPEC.md: share of drafted defenders that get a CFBD athlete id, with zero team contradictions

# CFBD names the drafting team by city. Two cities hold two franchises. Canonical codes as in team_aliases (the Rams are LA).
TEAM_CODES = {
    "Arizona": {"ARI"}, "Atlanta": {"ATL"}, "Baltimore": {"BAL"}, "Buffalo": {"BUF"}, "Carolina": {"CAR"}, "Chicago": {"CHI"},
    "Cincinnati": {"CIN"}, "Cleveland": {"CLE"}, "Dallas": {"DAL"}, "Denver": {"DEN"}, "Detroit": {"DET"}, "Green Bay": {"GB"},
    "Houston": {"HOU"}, "Indianapolis": {"IND"}, "Jacksonville": {"JAX"}, "Kansas City": {"KC"}, "Las Vegas": {"LV"},
    "Los Angeles": {"LAC", "LA"}, "Miami": {"MIA"}, "Minnesota": {"MIN"}, "New England": {"NE"}, "New Orleans": {"NO"},
    "New York": {"NYG", "NYJ"}, "Philadelphia": {"PHI"}, "Pittsburgh": {"PIT"}, "San Francisco": {"SF"}, "Seattle": {"SEA"},
    "Tampa Bay": {"TB"}, "Tennessee": {"TEN"}, "Washington": {"WAS"},
}


def build_bridge(conn) -> dict:
    if not conn.execute("SELECT 1 FROM core_nflverse_draft_picks LIMIT 1").fetchone() \
            or not conn.execute("SELECT 1 FROM core_cfbd_draft_picks LIMIT 1").fetchone():
        conn.execute("DELETE FROM mart_idp_prospect_cfbd_bridge")
        return {"failures": [], "summary": "no draft picks loaded"}
    resolve = _team_resolver(conn)
    cfbd = {(r["season"], r["overall"]): r for r in conn.execute("SELECT * FROM core_cfbd_draft_picks")}
    roster = {}
    for r in conn.execute("SELECT id, season, recruitIds FROM core_cfbd_roster WHERE recruitIds IS NOT NULL AND recruitIds != '[]'"):
        roster.setdefault(r["id"], []).append((r["season"], json.loads(r["recruitIds"])))
    recruits = {}
    for r in conn.execute("SELECT * FROM core_cfbd_recruiting_players"):
        recruits.setdefault(r["id"], []).append(r)
    pop = conn.execute("""SELECT gsis_id, season, pick, team FROM core_nflverse_draft_picks
                          WHERE side = 'D' AND season >= ? AND gsis_id IS NOT NULL ORDER BY season, pick""", (FIRST_DRAFT,)).fetchall()
    n_def = {}   # drafted defenders per class, with or without a gsis_id (the gate's denominator)
    for s, n in conn.execute("SELECT season, COUNT(*) FROM core_nflverse_draft_picks WHERE side = 'D' AND season >= ? GROUP BY season",
                             (FIRST_DRAFT,)):
        n_def[s] = n

    out, fails, unmapped, unknown_names = [], [], set(), set()
    for gsis, season, pick, team in pop:
        row = dict(gsis_id=gsis, draft_season=season, draft_pick=pick, cfbd_athlete_id=None, draft_status="ok", dp_pre_rank=None,
                   dp_pre_pos_rank=None, dp_pre_grade=None, recruit_id=None, recruit_status="no_bridge", rec_year=None,
                   rec_stars=None, rec_rating=None, rec_ranking=None)
        c = cfbd.get((season, pick))
        mine = resolve(team, season) if team else None
        if team and mine is None:
            unmapped.add(team)
        if c is None:
            row["draft_status"] = "no_cfbd_pick"
        elif c["collegeAthleteId"] is None:
            row["draft_status"] = "no_athlete_id"
        elif c["nflTeam"] not in TEAM_CODES:
            unknown_names.add(c["nflTeam"])
            row["draft_status"] = "team_contradiction"
        elif mine not in TEAM_CODES[c["nflTeam"]]:
            row["draft_status"] = "team_contradiction"
        else:
            aid = str(c["collegeAthleteId"])
            row.update(cfbd_athlete_id=aid, dp_pre_rank=c["preDraftRanking"], dp_pre_pos_rank=c["preDraftPositionRanking"],
                       dp_pre_grade=c["preDraftGrade"])
            ids = {i for s, lst in roster.get(aid, []) if s <= season - 1 for i in lst}
            if not ids:
                row["recruit_status"] = "no_roster_recruit_id"
            elif len(ids) > 1:
                row["recruit_status"] = "multi_recruit_id"
            else:
                rid = next(iter(ids))
                rows = recruits.get(rid, [])
                if len(rows) != 1:
                    row["recruit_status"] = "recruit_not_loaded"
                elif rows[0]["athleteId"] and rows[0]["athleteId"] != aid:
                    row["recruit_status"] = "athlete_disagrees"
                else:
                    r = rows[0]
                    row.update(recruit_id=rid, recruit_status="ok", rec_year=r["year"], rec_stars=r["stars"], rec_rating=r["rating"],
                               rec_ranking=r["ranking"])
        out.append(row)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(mart_idp_prospect_cfbd_bridge)")]
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM mart_idp_prospect_cfbd_bridge")
        conn.executemany(f"INSERT INTO mart_idp_prospect_cfbd_bridge ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [tuple(r[c] for c in cols) for r in out])
        fails = bridge_checks(conn, n_def)
        fails += [f"draft team code {t!r} is not in team_aliases" for t in sorted(unmapped)]
        fails += [f"CFBD team name {t!r} is not in TEAM_CODES" for t in sorted(unknown_names)]
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    ok = sum(1 for r in out if r["draft_status"] == "ok")
    rec = sum(1 for r in out if r["recruit_status"] == "ok")
    bad = sum(1 for r in out if r["draft_status"] == "team_contradiction")
    return {"failures": fails, "summary": f"{len(out)} drafted defenders {FIRST_DRAFT}+, {ok} with a CFBD athlete id, {bad} team contradiction(s), "
                                          f"{rec} with a recruit"}


def bridge_checks(conn, n_def) -> list[str]:
    fails = []
    # the gate: >= 95% of drafted defenders of the closed classes get an id, and no pair contradicts on the team
    tot = sum(n for s, n in n_def.items() if s <= GATE_LAST_DRAFT)
    got = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_cfbd_bridge WHERE draft_season <= ? AND draft_status = 'ok'",
                       (GATE_LAST_DRAFT,)).fetchone()[0]
    if tot and got < MIN_BRIDGE * tot:
        fails.append(f"bridge gate: {got}/{tot} drafted defenders 2017-{GATE_LAST_DRAFT} reach a CFBD athlete id, floor {MIN_BRIDGE:.0%}")
    bad = conn.execute("SELECT draft_season, gsis_id FROM mart_idp_prospect_cfbd_bridge WHERE draft_status = 'team_contradiction' "
                       "ORDER BY 1, 2").fetchall()
    if bad:
        fails.append(f"{len(bad)} team contradiction(s), e.g. {[tuple(r) for r in bad[:5]]}")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_cfbd_bridge WHERE (draft_status != 'ok' AND (cfbd_athlete_id IS NOT NULL "
                       "OR dp_pre_rank IS NOT NULL OR recruit_status != 'no_bridge')) OR (recruit_status = 'ok' AND (recruit_id IS NULL "
                       "OR rec_year IS NULL OR rec_year > draft_season - 1))").fetchone()[0]
    if bad:
        fails.append(f"{bad} bridge rows whose status disagrees with its data or whose recruit class is not before the draft")
    # one athlete id per player, and one player per athlete id
    bad = conn.execute("SELECT COUNT(*) FROM (SELECT cfbd_athlete_id FROM mart_idp_prospect_cfbd_bridge WHERE cfbd_athlete_id IS NOT NULL "
                       "GROUP BY cfbd_athlete_id HAVING COUNT(*) > 1)").fetchone()[0]
    if bad:
        fails.append(f"{bad} CFBD athlete ids bridged to more than one drafted defender")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_cfbd_bridge WHERE dp_pre_grade NOT BETWEEN 1 AND 100 "
                       "OR dp_pre_pos_rank < 1 OR dp_pre_rank < 1 OR rec_stars NOT BETWEEN 0 AND 5 OR rec_rating NOT BETWEEN 0 AND 1").fetchone()[0]
    if bad:
        fails.append(f"{bad} bridge rows with an implausible grade, rank, star count or rating")
    return fails
