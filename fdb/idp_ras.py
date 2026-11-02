"""Phase 17: the RAS bridge -> mart_idp_prospect_ras_bridge (builder `idp_prospect.ras_bridge`).

Every drafted defender 2017+ (core_nflverse_draft_picks side D, exact gsis_id) gets the RAS row for his (draft year, overall pick), where
the key allows it. A name is never read. What CAN reject a pair, and only reject it: the pick is listed more than once on the site, the
site's team is not the drafting team, the site's position is on the other side of the ball line (secondary vs front seven) from the draft
table's. A rejected pair leaves its RAS columns NULL and the status says why.
"""
from .idp_prospect import _team_resolver

FIRST_DRAFT = 2017           # the features start with the 2017 class; the 2016 draft table spells the Chargers SDG, which team_aliases does not map
GATE_FIRST, GATE_LAST = 2017, 2025
MIN_ACCEPTED = 0.90        # share of drafted defenders 2017-2025 whose pair is accepted
MAX_TEAM_REJECTS = 0.02    # a larger share rejected for team means the key is wrong, not that rows are

# The site names the franchise by nickname. Canonical codes as in team_aliases (the Rams are LA, the Raiders LV).
TEAM_CODES = {
    "49ers": "SF", "Bears": "CHI", "Bengals": "CIN", "Bills": "BUF", "Broncos": "DEN", "Browns": "CLE", "Buccaneers": "TB",
    "Cardinals": "ARI", "Chargers": "LAC", "Chiefs": "KC", "Colts": "IND", "Commanders": "WAS", "Cowboys": "DAL", "Dolphins": "MIA",
    "Eagles": "PHI", "Falcons": "ATL", "Giants": "NYG", "Jaguars": "JAX", "Jets": "NYJ", "Lions": "DET", "Packers": "GB",
    "Panthers": "CAR", "Patriots": "NE", "Raiders": "LV", "Rams": "LA", "Ravens": "BAL", "Saints": "NO", "Seahawks": "SEA",
    "Steelers": "PIT", "Texans": "HOU", "Titans": "TEN", "Vikings": "MIN",
}
FRONT = {"DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "MLB", "EDGE"}
BACK = {"CB", "DB", "S", "FS", "SS", "SAF"}


def _side(pos):
    return "front" if pos in FRONT else "back" if pos in BACK else None


def build_bridge(conn) -> dict:
    if not conn.execute("SELECT 1 FROM core_nflverse_draft_picks LIMIT 1").fetchone() \
            or not conn.execute("SELECT 1 FROM core_ras_maintable LIMIT 1").fetchone():
        conn.execute("DELETE FROM mart_idp_prospect_ras_bridge")
        return {"failures": [], "summary": "no draft picks or no RAS rows loaded"}
    resolve = _team_resolver(conn)
    by = {}
    for r in conn.execute("SELECT * FROM core_ras_maintable"):
        by.setdefault((r["YEAR"], r["PICK"]), []).append(r)
    pop = conn.execute("""SELECT gsis_id, season, pick, team, position FROM core_nflverse_draft_picks
                          WHERE side = 'D' AND season >= ? AND gsis_id IS NOT NULL ORDER BY season, pick""", (FIRST_DRAFT,)).fetchall()
    n_def = {}
    for s, n in conn.execute("SELECT season, COUNT(*) FROM core_nflverse_draft_picks WHERE side = 'D' AND season >= ? GROUP BY season",
                             (FIRST_DRAFT,)):
        n_def[s] = n
    out, unmapped, unknown = [], set(), set()
    for gsis, season, pick, team, pos in pop:
        row = dict(gsis_id=gsis, draft_season=season, draft_pick=pick, ras_status="ok", ras=None, ras_yd10=None, ras_yd20=None,
                   ras_yd40=None, ras_pos=None)
        mine = resolve(team, season) if team else None
        if team and mine is None:
            unmapped.add(team)
        hits = by.get((season, pick), [])
        if not hits:
            row["ras_status"] = "no_ras_row"
        elif len(hits) > 1:
            row["ras_status"] = "duplicate_key"
        else:
            h = hits[0]
            if h["TEAM"] not in TEAM_CODES:
                unknown.add(h["TEAM"])
                row["ras_status"] = "team_contradiction"
            elif TEAM_CODES[h["TEAM"]] != mine:
                row["ras_status"] = "team_contradiction"
            elif _side(h["POS"]) and _side(pos) and _side(h["POS"]) != _side(pos):
                row["ras_status"] = "side_contradiction"
            else:
                row.update(ras=h["RAS"], ras_yd10=h["YD10"], ras_yd20=h["YD20"], ras_yd40=h["YD40"], ras_pos=h["POS"])
        out.append(row)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(mart_idp_prospect_ras_bridge)")]
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM mart_idp_prospect_ras_bridge")
        conn.executemany(f"INSERT INTO mart_idp_prospect_ras_bridge ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [tuple(r[c] for c in cols) for r in out])
        fails = bridge_checks(conn, n_def)
        fails += [f"draft team code {t!r} is not in team_aliases" for t in sorted(unmapped)]
        fails += [f"RAS team name {t!r} is not in TEAM_CODES" for t in sorted(unknown)]
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    cnt = {}
    for r in out:
        cnt[r["ras_status"]] = cnt.get(r["ras_status"], 0) + 1
    scored = sum(1 for r in out if r["ras_status"] == "ok" and r["ras"] is not None)
    return {"failures": fails, "summary": f"{len(out)} drafted defenders {FIRST_DRAFT}+: {dict(sorted(cnt.items()))}, {scored} with a RAS score"}


def bridge_checks(conn, n_def) -> list[str]:
    fails = []
    tot = sum(n for s, n in n_def.items() if GATE_FIRST <= s <= GATE_LAST)
    ok = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_ras_bridge WHERE draft_season BETWEEN ? AND ? AND ras_status = 'ok'",
                      (GATE_FIRST, GATE_LAST)).fetchone()[0]
    if tot and ok < MIN_ACCEPTED * tot:
        fails.append(f"bridge gate: {ok}/{tot} drafted defenders {GATE_FIRST}-{GATE_LAST} accepted, floor {MIN_ACCEPTED:.0%}")
    team = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_ras_bridge WHERE draft_season BETWEEN ? AND ? "
                        "AND ras_status = 'team_contradiction'", (GATE_FIRST, GATE_LAST)).fetchone()[0]
    if tot and team > MAX_TEAM_REJECTS * tot:
        fails.append(f"{team} team contradictions of {tot} (ceiling {MAX_TEAM_REJECTS:.0%}): the (year, pick) key is not holding")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_ras_bridge WHERE (ras_status != 'ok' AND (ras IS NOT NULL OR ras_yd10 IS NOT NULL "
                       "OR ras_yd20 IS NOT NULL OR ras_yd40 IS NOT NULL OR ras_pos IS NOT NULL)) "
                       "OR (ras_status = 'ok' AND ras_pos IS NULL)").fetchone()[0]
    if bad:
        fails.append(f"{bad} bridge rows whose status disagrees with their data")
    bad = conn.execute("SELECT COUNT(*) FROM mart_idp_prospect_ras_bridge WHERE ras NOT BETWEEN 0 AND 10 OR ras_yd10 NOT BETWEEN 1.2 AND 2.3 "
                       "OR ras_yd20 NOT BETWEEN 2.0 AND 3.6 OR ras_yd40 NOT BETWEEN 4.0 AND 6.0").fetchone()[0]
    if bad:
        fails.append(f"{bad} bridge rows with an implausible score, split or forty")
    return fails
