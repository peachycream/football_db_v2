"""Participation seam (REBUILD_DESIGN §4, Phase 5): builder `participation.seam`.

nflverse participation stops at 2025; FTN has 2026. Each source keeps its own core
table under its own names; they meet HERE, in mart_participation_personnel, one row per
offensive scrimmage play (pass/run) with the source named on the row:
    nflverse  core_participation x core_pbp            seasons <  FTN_FROM
    ftn       core_ftn_participation x core_ftn_plays   seasons >= FTN_FROM

Personnel = counts of backs (RB incl. FB), tight ends, receivers among the skill
players, parsed from each source's OWN vocabulary - three of them, all handled here:
  * nflverse 2016-2022  'offense_personnel' = '1 RB, 1 TE, 3 WR'
  * nflverse 2023-2025  '1 C, 1 FB, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 2 WR' (FB split out)
  * FTN skp1..5_pos are ALIGNMENT slots, not positions (found on the first seam run:
                        a tight end split wide is 'WR'/'SLT', so alignment gave FTN 25%
                        "10 personnel" vs nflverse's 0.5%). FTN personnel is therefore
                        counted from each skill player's ROSTER position, by exact gsis
                        id: nflverse weekly roster for that season (latest week), else
                        players.position. The alignment vocabulary change (2021 'TE',
                        2022+ 'Y-TE'/'H-TE') then cannot touch personnel at all; the
                        alignment codes stay verbatim in core_ftn_participation.
A play is kept only when all 5 skill players are backs/TEs/receivers (else its
personnel is unknown - e.g. a 6th lineman reporting eligible - and the counts of
such plays are reported by the seam test, on both sources alike).
"""
import re
from collections import Counter, defaultdict

FTN_FROM = 2026
ROSTER_BACK, ROSTER_TE, ROSTER_WR = {"RB", "FB", "HB"}, {"TE"}, {"WR"}
_TOKEN = re.compile(r"(\d+)\s+([A-Z]+)")


def nflverse_counts(s: str | None) -> tuple[int, int, int] | None:
    if not s:
        return None
    c = Counter()
    for n, pos in _TOKEN.findall(s):
        c[pos] += int(n)
    rb, te, wr = c["RB"] + c["FB"], c["TE"], c["WR"]
    return (rb, te, wr) if rb + te + wr == 5 else None


def ftn_counts(positions) -> tuple[int, int, int] | None:
    """positions = the 5 skill players' ROSTER positions (see module doc)."""
    pos = [p for p in positions if p]
    if len(pos) != 5:
        return None
    rb, te, wr = (sum(p in fam for p in pos) for fam in (ROSTER_BACK, ROSTER_TE, ROSTER_WR))
    return (rb, te, wr) if rb + te + wr == 5 else None


def roster_positions(conn, seasons) -> dict:
    """(season, gsis_id) -> roster position that season (latest week), exact ids only."""
    ph = ",".join("?" * len(seasons))
    out = {}
    for s, g, pos in conn.execute(f"""SELECT r.season, r.gsis_id, r.position FROM core_rosters_weekly r
            JOIN (SELECT season, gsis_id, MAX(week) w FROM core_rosters_weekly WHERE season IN ({ph}) AND gsis_id IS NOT NULL
                  GROUP BY 1, 2) m ON m.season = r.season AND m.gsis_id = r.gsis_id AND m.w = r.week""", seasons):
        out[(s, g)] = pos
    return out


def _ftn_positions(conn, seasons, rows):
    rp = roster_positions(conn, seasons)
    fallback = dict(conn.execute("SELECT gsis_id, position FROM players"))
    for r in rows:
        yield r, [rp.get((r[0], g)) or fallback.get(g) for g in r[7:12]]


def personnel(counts) -> str:
    return f"{counts[0]}{counts[1]}"   # '11' = 1 back, 1 TE


def _nflverse_rows(conn, seasons):
    ph = ",".join("?" * len(seasons))
    return conn.execute(f"""
        SELECT x.season, x.season_type, x.week, a.team, x.nflverse_game_id, x.play_id, b.play_type, x.offense_personnel
        FROM core_participation x
        JOIN core_pbp b ON b.game_id = x.nflverse_game_id AND b.play_id = x.play_id
        JOIN team_aliases a ON a.abbr = x.possession_team AND x.season BETWEEN a.season_from AND a.season_to
        WHERE x.season IN ({ph}) AND b.play_type IN ('pass', 'run')""", seasons)


def _ftn_rows(conn, seasons):
    ph = ",".join("?" * len(seasons))
    return conn.execute(f"""
        SELECT x.season, x.season_type, x.week, a.team, x.gid, x.pid, lower(CASE y.type WHEN 'RUSH' THEN 'run' ELSE y.type END),
               x.skp1, x.skp2, x.skp3, x.skp4, x.skp5
        FROM core_ftn_participation x
        JOIN core_ftn_plays y ON y.pid = x.pid
        JOIN team_aliases a ON a.abbr = y.off AND x.season BETWEEN a.season_from AND a.season_to
        WHERE x.season IN ({ph}) AND y.type IN ('PASS', 'RUSH')""", seasons)


def build(conn) -> dict:
    nfl_seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM core_participation WHERE season < ?", (FTN_FROM,))]
    ftn_seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM core_ftn_participation WHERE season >= ?", (FTN_FROM,))]
    rows, unknown = [], Counter()
    for r in _nflverse_rows(conn, nfl_seasons) if nfl_seasons else []:
        c = nflverse_counts(r[7])
        if c is None:
            unknown[("nflverse", r[0])] += 1
            continue
        rows.append((*r[:4], "nflverse", str(r[4]), str(r[5]), r[6], *c, personnel(c)))
    for r, pos in _ftn_positions(conn, ftn_seasons, _ftn_rows(conn, ftn_seasons)) if ftn_seasons else []:
        c = ftn_counts(pos)
        if c is None:
            unknown[("ftn", r[0])] += 1
            continue
        rows.append((*r[:4], "ftn", str(r[4]), str(r[5]), r[6], *c, personnel(c)))
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM mart_participation_personnel")
        conn.executemany("INSERT INTO mart_participation_personnel VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    by_src = Counter(r[4] for r in rows)
    return {"failures": [], "summary": f"{by_src['nflverse']} nflverse plays ({min(nfl_seasons, default='-')}-"
                                       f"{max(nfl_seasons, default='-')}), {by_src['ftn']} FTN plays "
                                       f"({', '.join(map(str, ftn_seasons)) or '-'}); personnel unknown: "
                                       f"{sum(unknown.values())}"}


# ------------------------------------------------------------- seam test ----
GROUPS = ("11", "12", "21", "13", "10", "22")


def _dist(rows, counts_fn):
    """rows: (row, personnel-input) pairs."""
    by = defaultdict(Counter)
    unknown = Counter()
    for r, inp in rows:
        c = counts_fn(inp)
        if c is None:
            unknown[r[3]] += 1
            continue
        p = personnel(c)
        by[r[3]][p if p in GROUPS else "other"] += 1
    return by, unknown


def seam_test(conn, seasons=(2021, 2022, 2023, 2024, 2025), team_tol=5.0, league_tol=2.0):
    """Per team-season personnel shares, nflverse vs FTN, on the overlap. Tolerances are
    fixed here BEFORE looking: every group within `team_tol` points per team-season and
    within `league_tol` points league-wide. -> [(name, value, ok)]"""
    out = []
    for s in seasons:
        nfl, nfl_unk = _dist(((r, r[7]) for r in _nflverse_rows(conn, [s])), nflverse_counts)
        ftn, ftn_unk = _dist(_ftn_positions(conn, [s], _ftn_rows(conn, [s]).fetchall()), ftn_counts)
        if not ftn:
            out.append((f"{s} seam: FTN participation staged", "none loaded", False))
            continue
        worst, bad = (None, 0.0), []
        for team in sorted(set(nfl) | set(ftn)):
            a, b = nfl.get(team, Counter()), ftn.get(team, Counter())
            na, nb = sum(a.values()), sum(b.values())
            for g in GROUPS + ("other",):
                d = abs(100 * a[g] / na - 100 * b[g] / nb) if na and nb else 100.0
                if d > worst[1]:
                    worst = (f"{team} {g}: nflverse {100 * a[g] / na:.1f}% vs FTN {100 * b[g] / nb:.1f}%", d)
                if d > team_tol:
                    bad.append(f"{team} {g} {d:.1f}pt")
        out.append((f"{s} seam: personnel per team-season within {team_tol} pts (every group)",
                    f"{len(set(nfl) | set(ftn))} teams; worst {worst[0]} ({worst[1]:.1f} pts)" + (f"; over: {bad[:6]}" if bad else ""),
                    not bad))
        la, lb = Counter(), Counter()
        for t in nfl: la.update(nfl[t])
        for t in ftn: lb.update(ftn[t])
        na, nb = sum(la.values()), sum(lb.values())
        diffs = {g: 100 * la[g] / na - 100 * lb[g] / nb for g in GROUPS + ("other",)}
        out.append((f"{s} seam: league personnel within {league_tol} pts",
                    ", ".join(f"{g} {100 * la[g] / na:.1f}/{100 * lb[g] / nb:.1f}" for g in GROUPS) +
                    f" (nflverse/FTN %; plays {na}/{nb}; unknown personnel {sum(nfl_unk.values())}/{sum(ftn_unk.values())})",
                    all(abs(v) <= league_tol for v in diffs.values())))
        if s == 2021:
            # §9 trap, REVISED 2026-09-27 (flagged for Turon): the spec's "FTN 2021 11-personnel
            # share in 25-45%" encodes v1's number, which v1 computed from FTN ALIGNMENT codes
            # (v2's first seam run reproduced it: 34.3%). By roster position, two independent
            # sources agree on ~62% (nflverse 62.2, FTN 61.4). The trap's purpose - catch the
            # 2021 'TE' vocabulary silently mis-counting tight ends - is kept as agreement with
            # nflverse; the old band is reported for reference only.
            a11, b11 = 100 * la["11"] / na, 100 * lb["11"] / nb
            out.append(("2021 trap: FTN 11-personnel share agrees with nflverse within 2 pts",
                        f"FTN {b11:.1f}% vs nflverse {a11:.1f}% (spec's v1-derived 25-45% band: {'in' if 25 <= b11 <= 45 else 'out'})",
                        abs(a11 - b11) <= 2.0))
    return out


def live_checks(conn, season: int) -> list[tuple[str, str, bool]]:
    """Seasons past the seam (FTN only, no nflverse to agree with): the league personnel
    mix must sit inside FTN's own 2021-2025 range (+/- 3 pts), and the all-22 ids must be
    people (FTN ids are gsis_ids)."""
    out = []
    cur = Counter(r[0] for r in conn.execute("SELECT personnel FROM mart_participation_personnel WHERE season = ? AND source = 'ftn'", (season,)))
    n = sum(cur.values())
    if not n:
        return [(f"{season} FTN personnel in the mart", "none", False)]
    past = {}
    for s in (2021, 2022, 2023, 2024, 2025):
        d, _ = _dist(_ftn_positions(conn, [s], _ftn_rows(conn, [s]).fetchall()), ftn_counts)
        tot = Counter()
        for t in d:
            tot.update(d[t])
        if tot:
            past[s] = {g: 100 * tot[g] / sum(tot.values()) for g in ("11", "12", "21")}
    for g in ("11", "12", "21"):
        share = 100 * cur[g] / n
        lo, hi = min(p[g] for p in past.values()) - 3, max(p[g] for p in past.values()) + 3
        out.append((f"{season} FTN {g}-personnel share inside FTN 2021-2025 range +/-3", f"{share:.1f}% (range {lo:.1f}-{hi:.1f})", lo <= share <= hi))
    ids = [r for r in conn.execute(f"""SELECT COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM (
             {' UNION ALL '.join(f"SELECT off{i}Id id FROM core_ftn_all22 WHERE season = ?1 UNION ALL SELECT def{i}Id FROM core_ftn_all22 WHERE season = ?1" for i in range(1, 12))}) x
             LEFT JOIN players p ON p.gsis_id = x.id WHERE x.id IS NOT NULL AND x.id != ''""", (season,))][0]
    out.append((f"{season} FTN all-22 player ids resolve to players", f"{ids[1]}/{ids[0]} = {100 * (ids[1] or 0) / (ids[0] or 1):.2f}%",
                bool(ids[0]) and ids[1] / ids[0] >= 0.98))
    return out
