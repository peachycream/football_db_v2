"""Builder `matchup.build`: mart_matchup_card (+ _groups, _players), the Matchup of the Week card's data.
Schema and column meanings: schema/028_mart_matchup_card.sql. Everything is read from core_* tables:
core_mfl_weekly_results / _lineups (completed weeks), core_mfl_upcoming_* (the next unplayed week),
core_mfl_projected_scores (snapshots), core_mfl_franchises / _divisions / _league, core_schedule; players are
joined through player_ids(mfl) only (an unresolved id keeps its MFL id and no name; nothing is matched by name)."""
import re
import tomllib
from collections import defaultdict
from datetime import datetime, timezone

from . import config, schedule
from .timeutil import eastern_to_utc, utcnow

COLORS_PATH = config.ROOT / "config" / "franchise_colors.toml"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
RESULTS = ("W", "L", "T")
STATES = ("PREVIEW", "LIVE", "FINAL")
MAX_UNGROUPED = 0.01   # share of starters whose position the mapping does not know (reported; above this the build fails)

# Position code -> card group. A mapping of position CODES (v1's POS_GROUP plus K/PK), not of names.
POS_GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "K": "PK", "PK": "PK",
             "DE": "DL", "DT": "DL", "ED": "DL", "EDGE": "DL", "DI": "DL", "NT": "DL", "DL": "DL", "IDL": "DL",
             "LB": "LB", "ILB": "LB", "MLB": "LB", "OLB": "LB",
             "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB", "SAF": "DB"}


def strip_markup(s):
    """MFL franchise names can carry HTML ('<font color=...>Baltimore Ravens</font> '): a cast of a label to text."""
    return re.sub(r"<[^>]+>", "", s or "").strip()


def stamp_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)


def load_colors() -> dict:
    with open(COLORS_PATH, "rb") as f:
        rows = tomllib.load(f).get("color", [])
    return {(str(r["league_id"]), str(r["franchise_id"])): (r["color"], r.get("alt")) for r in rows}


class Data:
    """Everything the builder needs, read once."""

    def __init__(self, conn):
        q = lambda sql, *a: conn.execute(sql, a).fetchall()
        self.fr = {(r["season"], r["league_id"], r["id"]): r for r in q(
            "SELECT season, league_id, id, name, abbrev, division, logo, icon FROM core_mfl_franchises")}
        self.div_name = {(r["season"], r["league_id"], r["id"]): r["name"] for r in q(
            "SELECT season, league_id, id, name FROM core_mfl_divisions")}
        self.last_reg = {(r["season"], r["league_id"]): r["lastRegularSeasonWeek"] for r in q(
            "SELECT season, league_id, lastRegularSeasonWeek FROM core_mfl_league")}
        self.results = q("""SELECT season, league_id, week, id, opponent_id, isHome, score, adj_score, result, opt_pts
                            FROM core_mfl_weekly_results""")
        # newest upcoming snapshot per (season, league, week) for the pairings and lineups
        self.up_games, self.up_lineups, self.up_snap = defaultdict(list), defaultdict(list), {}
        for r in q("SELECT season, league_id, week, MAX(snapshot_at) s FROM core_mfl_upcoming_games GROUP BY 1, 2, 3"):
            self.up_snap[(r["season"], r["league_id"], r["week"])] = r["s"]
        for r in q("SELECT season, league_id, week, snapshot_at, id, opponent_id, isHome FROM core_mfl_upcoming_games"):
            if self.up_snap.get((r["season"], r["league_id"], r["week"])) == r["snapshot_at"]:
                self.up_games[(r["season"], r["league_id"], r["week"])].append(r)
        self.up_roster = defaultdict(lambda: defaultdict(list))           # (s, l, w) -> franchise -> [(id, None)], every status
        for r in q("SELECT season, league_id, week, snapshot_at, franchise_id, id, status FROM core_mfl_upcoming_lineups"):
            if self.up_snap.get((r["season"], r["league_id"], r["week"])) == r["snapshot_at"]:
                self.up_lineups[(r["season"], r["league_id"], r["week"])].append(r)
                self.up_roster[(r["season"], r["league_id"], r["week"])][r["franchise_id"]].append((r["id"], None))
        self.lineups = defaultdict(list)                                  # starters
        self.roster = defaultdict(lambda: defaultdict(list))              # (s, l, w) -> franchise -> [(id, actual)], every status
        for r in q("SELECT season, league_id, week, franchise_id, id, score, status FROM core_mfl_lineups"):
            k = (r["season"], r["league_id"], r["week"])
            self.roster[k][r["franchise_id"]].append((r["id"], r["score"]))
            if r["status"] == "starter":
                self.lineups[k].append(r)
        self.player = {r["source_id"]: r for r in q(
            """SELECT i.source_id, i.gsis_id, p.display_name, p.position FROM player_ids i
               JOIN players p ON p.gsis_id = i.gsis_id WHERE i.source = 'mfl'""")}
        # first kickoff and completeness per (season, week), regular season only
        self.kick, self.complete = {}, {}
        for s in {r["season"] for r in q("SELECT DISTINCT season FROM core_schedule")}:
            self.complete[s] = {w for t, w in schedule.completed_weeks(conn, s) if t == "REG"}
        for r in q("SELECT season, week, gameday, gametime FROM core_schedule WHERE season_type = 'REG'"):
            k = eastern_to_utc(r["gameday"], r["gametime"])
            key = (r["season"], r["week"])
            self.kick[key] = min(self.kick.get(key, k), k)
        # projection snapshots: (season, league, week) -> [(snapshot_at, {player id: score})], oldest first
        snaps = defaultdict(lambda: defaultdict(dict))
        for r in q("SELECT season, league_id, week, snapshot_at, id, score FROM core_mfl_projected_scores"):
            snaps[(r["season"], r["league_id"], r["week"])][r["snapshot_at"]][r["id"]] = r["score"]
        self.proj = {k: sorted(v.items()) for k, v in snaps.items()}
        self.colors = load_colors()

    def pre_kickoff_projection(self, season, league, week):
        """(snapshot_at, {id: score}) of the LAST snapshot taken before the week's first kickoff, else None."""
        kick = self.kick.get((season, week))
        best = None
        for s, m in self.proj.get((season, league, week), []):
            if kick is not None and stamp_utc(s) < kick:
                best = (s, m)
        return best


def games_of(rows, home_key="isHome"):
    """Unordered pairs from per-franchise-per-game rows -> {(season, league, week): [(home, away, defect)]}.
    home = the franchise flagged isHome; a pair without exactly one home flag falls back to the lower id (counted)."""
    flags = defaultdict(dict)
    for r in rows:
        if r["opponent_id"] == "":
            continue
        flags[(r["season"], r["league_id"], r["week"])][(r["id"], r["opponent_id"])] = r[home_key]
    out = defaultdict(list)
    for key, m in flags.items():
        done = set()
        for (a, b), ha in m.items():
            if (b, a) in done or (a, b) in done:
                continue
            done.add((a, b))
            hb = m.get((b, a))
            if ha == 1 and hb != 1:
                out[key].append((a, b, False))
            elif hb == 1 and ha != 1:
                out[key].append((b, a, False))
            else:
                out[key].append((min(a, b), max(a, b), True))
    return out


def build(conn) -> dict:
    d = Data(conn)
    now = utcnow()
    fails: list[str] = []
    stats = defaultdict(int)

    # ---- per-franchise history from reported results (regular season only) ----------------------------
    by_fr = defaultdict(list)      # (season, league, id) -> [(week, result, score, opponent)]
    score_of = {}                  # (season, league, week, id) -> score (a week's points once)
    for r in d.results:
        if r["result"] not in RESULTS:
            fails.append(f"{r['season']}/{r['league_id']} wk{r['week']} {r['id']}: unknown result {r['result']!r}")
        if r["week"] <= (d.last_reg.get((r["season"], r["league_id"])) or 0):
            by_fr[(r["season"], r["league_id"], r["id"])].append((r["week"], r["result"], r["score"], r["opponent_id"]))
        score_of[(r["season"], r["league_id"], r["week"], r["id"])] = r["score"]

    def record_before(season, league, fid, week):
        w = l = t = 0
        n = 0
        for wk, res, _, _ in by_fr.get((season, league, fid), ()):
            if wk < week:
                n += 1
                w += res == "W"; l += res == "L"; t += res == "T"
        return w, l, t, n

    pf_by = defaultdict(dict)      # (season, league, id) -> {week: score}, regular season
    for (s, lg, wk, f), sc in score_of.items():
        if wk <= (d.last_reg.get((s, lg)) or 0):
            pf_by[(s, lg, f)][wk] = sc

    # ---- meetings between two franchises (regular season), oldest first -------------------------------
    meet = defaultdict(list)       # (league, frozenset({a, b})) -> [(season, week, {id: score})]
    sc_pair = defaultdict(dict)
    for r in d.results:
        if r["opponent_id"] != "":
            sc_pair[(r["season"], r["league_id"], r["week"], frozenset((r["id"], r["opponent_id"])))][r["id"]] = r["score"]
    for (s, lg, wk, pair), m in sc_pair.items():
        if wk <= (d.last_reg.get((s, lg)) or 0) and len(m) == 2:
            meet[(lg, pair)].append((s, wk, m))
    for v in meet.values():
        v.sort(key=lambda x: (x[0], x[1]))

    def series(league, a, b, season, week):
        w_a = w_b = t = 0
        last = None
        for s, wk, m in meet.get((league, frozenset((a, b))), ()):
            if (s, wk) >= (season, week):
                break
            if m[a] > m[b]:
                w_a += 1
            elif m[b] > m[a]:
                w_b += 1
            else:
                t += 1
            last = (s, wk, m[a], m[b])
        return w_a, w_b, t, last

    # ---- game list: every completed game, plus the games of the newest upcoming snapshot per week -----
    games = []   # (season, league, week, home, away, source) source: 'weekly_results' | 'upcoming_snapshot'
    for key, lst in games_of(d.results).items():
        for h, a, defect in lst:
            stats["home_flag_fallback"] += defect
            games.append((*key, h, a, "weekly_results"))
    have = {(g[0], g[1], g[2]) for g in games}
    for key, rows in d.up_games.items():
        if key in have:
            continue   # the week is already in weekly_results; its actuals win over a pre-game snapshot
        for h, a, defect in games_of([{**dict(r), "season": key[0], "league_id": key[1], "week": key[2]} for r in rows])[key]:
            stats["home_flag_fallback"] += defect
            games.append((*key, h, a, "upcoming_snapshot"))

    # ---- lineups (per franchise-week) -> groups and players -------------------------------------------
    lineup_rows = {}   # (season, league, week) -> {franchise: [(pid, actual_or_None)]}
    for key, rows in d.lineups.items():
        by = defaultdict(list)
        for r in rows:
            by[r["franchise_id"]].append((r["id"], r["score"]))
        lineup_rows[key] = by
    for key, rows in d.up_lineups.items():
        if key in lineup_rows:
            continue
        by = defaultdict(list)
        for r in rows:
            if r["status"] == "starter":
                by[r["franchise_id"]].append((r["id"], None))
        lineup_rows[key] = by

    card, groups, players = [], [], []
    wanted = {(g[0], g[1], g[2], f) for g in games for f in (g[3], g[4])}
    ungrouped, starters_total = [], 0
    proj_used = {}
    for (season, league, week), by in lineup_rows.items():
        proj = d.pre_kickoff_projection(season, league, week)
        proj_used[(season, league, week)] = proj
        pm = proj[1] if proj else None
        for fid, plist in by.items():
            if (season, league, week, fid) not in wanted:
                continue
            g = defaultdict(lambda: {"n": 0, "proj": None, "actual": None})
            for pid, actual in plist:
                info = d.player.get(pid)
                pos = info["position"] if info else None
                grp = POS_GROUP.get(pos) if pos else None
                starters_total += 1
                if grp is None:
                    grp = "OTHER"
                    ungrouped.append((season, league, week, fid, pid, pos))
                pr = pm.get(pid) if pm is not None else None
                players.append((season, league, week, fid, pid, info["gsis_id"] if info else None,
                                info["display_name"] if info else None, pos, grp, pr, actual))
                x = g[grp]
                x["n"] += 1
                if actual is not None:
                    x["actual"] = (x["actual"] or 0.0) + actual
                if pr is not None:
                    x["proj"] = (x["proj"] or 0.0) + pr
            groups += [(season, league, week, fid, k, v["n"], v["proj"], v["actual"]) for k, v in sorted(g.items())]

    # ---- one card row per game -------------------------------------------------------------------------
    proj_total = defaultdict(lambda: (None, 0))
    for (s, lg, wk, fid, pid, gs, nm, pos, grp, pr, ac) in players:
        t, miss = proj_total[(s, lg, wk, fid)]
        proj_total[(s, lg, wk, fid)] = ((t or 0.0) + pr if pr is not None else t, miss + (pr is None))
    res_row = {}
    for r in d.results:
        res_row[(r["season"], r["league_id"], r["week"], r["id"])] = r
    for (season, league, week, home, away, source) in games:
        kick = d.kick.get((season, week))
        complete = week in d.complete.get(season, set())
        # FINAL means RESULTS ARE LOADED (core_mfl_weekly_results has the week), not merely "the schedule says the week is
        # over". A week that is complete per the schedule but whose results the weekly job has not loaded yet (Monday night
        # settles Wednesday 00:15 ET, the job runs 05:00) stays LIVE: it has pairings and lineups but no scores, and a FINAL
        # row without scores would be a lie that fails the build. The recap picker therefore waits for FINAL.
        if source == "weekly_results":
            state = "FINAL"
        else:
            state = "LIVE" if (complete or (kick is not None and now >= kick)) else "PREVIEW"
            stats["awaiting_results"] += complete
        if source == "weekly_results" and not complete:
            fails.append(f"{season}/{league} wk{week}: results loaded for a week the schedule says is not complete")
        sides = {}
        for who, fid in (("home", home), ("away", away)):
            f = d.fr.get((season, league, fid))
            w, l, t, n = record_before(season, league, fid, week)
            pfs = pf_by.get((season, league, fid), {})
            col = d.colors.get((league, fid), (None, None))
            sides[who] = dict(
                id=fid, name=strip_markup(f["name"]) if f else None, abbrev=f["abbrev"] if f else None,
                division=d.div_name.get((season, league, f["division"])) if f else None,
                logo=(f["logo"] or None) if f else None, icon=(f["icon"] or None) if f else None,
                color=col[0], alt=col[1], w=w, l=l, t=t, n=n, pf=round(sum(v for wk, v in pfs.items() if wk < week), 2),
                div_id=f["division"] if f else None)
        rv = {who: res_row.get((season, league, week, sides[who]["id"])) for who in ("home", "away")}
        score = {k: (v["score"] if (v is not None and state == "FINAL") else None) for k, v in rv.items()}
        opt = {k: (v["opt_pts"] if (v is not None and state == "FINAL") else None) for k, v in rv.items()}
        pj = {who: proj_total.get((season, league, week, sides[who]["id"]), (None, 0)) for who in ("home", "away")}
        snap = proj_used.get((season, league, week))
        roster = d.roster if source == "weekly_results" else d.up_roster
        pm_ = snap[1] if snap else None
        strength, roster_actual = {}, {}
        for who in ("home", "away"):
            ids = roster.get((season, league, week), {}).get(sides[who]["id"], [])
            strength[who] = round(sum(pm_.get(i, 0.0) or 0.0 for i, _ in ids), 2) if (pm_ is not None and ids) else None
            roster_actual[who] = round(sum(a or 0.0 for _, a in ids), 2) if (state == "FINAL" and ids) else None
        is_playoff = int(week > (d.last_reg.get((season, league)) or 0))
        w_h, w_a, t_, last = series(league, home, away, season, week)
        rival = int(bool(sides["home"]["div_id"]) and sides["home"]["div_id"] == sides["away"]["div_id"])
        H, A = sides["home"], sides["away"]
        card.append((season, league, week, "REG", state, kick.strftime("%Y-%m-%dT%H:%M:%SZ") if kick else None, rival,
                     source, d.up_snap.get((season, league, week)) if source == "upcoming_snapshot" else None,
                     snap[0] if snap else None,
                     H["id"], H["name"], H["abbrev"], H["division"], H["logo"], H["icon"], H["color"], H["alt"],
                     A["id"], A["name"], A["abbrev"], A["division"], A["logo"], A["icon"], A["color"], A["alt"],
                     H["w"], H["l"], H["t"], H["pf"], A["w"], A["l"], A["t"], A["pf"],
                     score["home"], score["away"], opt["home"], opt["away"],
                     pj["home"][0] if snap else None, pj["away"][0] if snap else None,
                     pj["home"][1] if snap else None, pj["away"][1] if snap else None,
                     w_h + w_a + t_, w_h, w_a, t_, last[0] if last else None, last[1] if last else None,
                     last[2] if last else None, last[3] if last else None,
                     is_playoff, strength["home"], strength["away"], roster_actual["home"], roster_actual["away"]))
        # invariants checked per game
        for who in ("home", "away"):
            s_ = sides[who]
            if s_["w"] + s_["l"] + s_["t"] != s_["n"]:
                fails.append(f"{season}/{league} wk{week} {s_['id']}: record {s_['w']}-{s_['l']}-{s_['t']} != {s_['n']} games")
        if state == "FINAL" and any(v is None for v in score.values()):
            fails.append(f"{season}/{league} wk{week} {home} v {away}: FINAL with a missing score {score}")
        # A REAL 0.00 exists (a franchise that set no lineup: 30590 2022 wk9 0021). It is allowed only because the
        # starters' actuals reconcile to the score (checked below), and it is counted, not hidden.
        stats["final_zero_scores"] += state == "FINAL" and any(v == 0 for v in score.values())
    # ---- cross-checks ----------------------------------------------------------------------------------
    n_pairs = len({(g[0], g[1], g[2], frozenset(g[3:5])) for g in games})
    if n_pairs != len(card):
        fails.append(f"{len(card)} card rows for {n_pairs} distinct games")
    # a group total must equal the starters' own total: grouping loses nothing
    by_total = defaultdict(float)
    for (s, lg, wk, fid, pid, gs, nm, pos, grp, pr, ac) in players:
        by_total[(s, lg, wk, fid)] += ac or 0.0
    g_total = defaultdict(float)
    for (s, lg, wk, fid, grp, n, pr, ac) in groups:
        g_total[(s, lg, wk, fid)] += ac or 0.0
    for k in by_total:
        if abs(by_total[k] - g_total[k]) > 0.011:
            fails.append(f"{k}: groups total {g_total[k]:.2f} != starters total {by_total[k]:.2f}")
            break
    # FINAL: the starters' actuals add to the franchise's reported score (adjustment included)
    bad = 0
    for (season, league, week, home, away, source) in games:
        if source != "weekly_results":
            continue
        for fid in (home, away):
            r = res_row.get((season, league, week, fid))
            if r is not None and (season, league, week, fid) in by_total:
                if abs(by_total[(season, league, week, fid)] + (r["adj_score"] or 0.0) - r["score"]) > 0.011:
                    bad += 1
    if bad:
        fails.append(f"{bad} franchise-weeks where the starters' actuals do not add to the reported score")
    if starters_total and len(ungrouped) / starters_total > MAX_UNGROUPED:
        fails.append(f"{len(ungrouped)} of {starters_total} starters ({len(ungrouped) / starters_total:.1%}) have no known position group, "
                     f"e.g. {ungrouped[:3]}")
    # colors: every configured franchise must exist in that league
    known = {(lg, f) for (_, lg, f) in d.fr}
    leagues_held = {lg for (lg, _) in known}   # only a league whose franchises are loaded can contradict the file
    for key in d.colors:
        if key[0] in leagues_held and key not in known:
            fails.append(f"config/franchise_colors.toml: franchise {key} is not in core_mfl_franchises")
    for key, (c, a) in d.colors.items():
        for v in (c, a):
            if v is not None and not HEX.match(v):
                fails.append(f"config/franchise_colors.toml: {key} has an invalid color {v!r}")

    conn.execute("BEGIN")
    try:
        for tbl, rows in (("mart_matchup_card", card), ("mart_matchup_card_groups", groups), ("mart_matchup_card_players", players)):
            conn.execute(f"DELETE FROM {tbl}")
            if rows:
                marks = ",".join("?" * len(rows[0]))
                conn.executemany(f"INSERT INTO {tbl} VALUES ({marks})", rows)
        conn.execute("ROLLBACK" if fails else "COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    by_state = defaultdict(int)
    for row in card:
        by_state[row[4]] += 1
    summary = (f"{len(card)} games ({', '.join(f'{k} {v}' for k, v in sorted(by_state.items()))}), {len(groups)} group rows, "
               f"{len(players)} starter rows; {len(ungrouped)} ungrouped starters; "
               f"{sum(1 for r in card if r[9])} games with a pre-kickoff projection; "
               f"{stats['final_zero_scores']} FINAL games with a real 0.00 side; "
               f"{stats['awaiting_results']} complete-per-schedule games awaiting their results")
    return {"failures": fails[:20], "summary": summary, "ungrouped": ungrouped[:20]}
