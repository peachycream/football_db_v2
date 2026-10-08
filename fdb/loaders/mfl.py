"""MyFantasyLeague loaders (Phase 3). Client and live-verified source facts: fdb/mfl.py.

One TYPE=league fetch feeds four tables: mfl.league fetches it; mfl.divisions,
mfl.conferences and mfl.franchises read the same raw file (`fetches = False`),
so MFL is called once per league, not four times.
"""
import json
from collections import defaultdict
from datetime import timedelta

from .. import config, mfl as api, schedule
from ..raw import records as raw_records
from ..loader import Loader, Scope
from ..timeutil import eastern_to_utc, utcnow

POOL_UNITS = ("LEAGUE", "CONFERENCE", "DIVISION")
ROSTER_STATUSES = ("ROSTER", "TAXI_SQUAD", "INJURED_RESERVE")
# MFL applies stat corrections for days after a week; its reported scores are
# treated as final only this long after the week's last kickoff.
SCORES_SETTLE = timedelta(days=7)


def _canon(v):
    """MFL shuffles key AND repeated-element order between calls (XML-to-JSON). For
    nested settings kept as JSON text, sort both so an unchanged setting stores
    unchanged text - the order carries no meaning in these elements."""
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return sorted((_canon(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
    return v


def _text(v):
    """MFL XML-to-JSON text node {"$t": x} -> x (a cast, not a rename)."""
    return v.get("$t") if isinstance(v, dict) and set(v) == {"$t"} else v


class MflLoader(Loader):
    source = "mfl"
    ext = "json"
    grain = "league"
    mfl_type = ""                  # TYPE= for the export call
    mfl_params: dict = {}

    def __init__(self):
        if not self.endpoint:
            self.endpoint = self.mfl_type

    # -- partitions: <season>/<league>[/week<n>] ------------------------------
    def partition(self, scope: Scope) -> str:
        return f"{scope.season}/{scope.league}"

    @staticmethod
    def _split(partition: str) -> tuple[int, str]:
        season, league = partition.split("/")[:2]
        return int(season), league

    def fetch(self, partition):
        season, league = self._split(partition)
        return api.export(season, league, self.mfl_type, **self.mfl_params)

    def raw_is_final(self, conn, partition):
        return schedule.season_is_closed(conn, self._split(partition)[0])

    def scope_where(self, scope):
        return "season = ? AND league_id = ?", (scope.season, scope.league)

    def derive(self, row):
        return {"season": self.scope.season, "league_id": self.scope.league}

    def scope_rows(self, rows, scope):
        return rows

    @staticmethod
    def _league_payload(payload: bytes) -> dict:
        return json.loads(payload)["league"]


# ---------------------------------------------------------------- league ----
class LeagueLoader(MflLoader):
    id = "mfl.league"
    history = True   # Phase 11: matchup history needs the league's closed seasons
    table = "core_mfl_league"
    mfl_type = "league"
    warn_new_fields = False   # scalar settings subset; UI prefs deliberately not stored
    JSON_FIELDS = ("starters", "rosterLimits")

    def parse(self, payload):
        lg = self._league_payload(payload)
        row = {k: v for k, v in lg.items() if not isinstance(v, (dict, list))}
        for k in self.JSON_FIELDS:
            if k in lg:
                row[k] = json.dumps(_canon(lg[k]), sort_keys=True)
        return list(lg.keys()), [row]

    def checks(self, conn, scope):
        r = conn.execute("SELECT id, playerLimitUnit, rostersPerPlayer FROM core_mfl_league "
                         "WHERE season = ? AND league_id = ?", (scope.season, scope.league)).fetchone()
        fails = []
        if r["id"] != scope.league:
            fails.append(f"{scope.label}: payload is league {r['id']}, not {scope.league}")
        if r["playerLimitUnit"] not in POOL_UNITS:
            fails.append(f"{scope.label}: unknown playerLimitUnit {r['playerLimitUnit']!r} (pool model unknown)")
        if not r["rostersPerPlayer"] or r["rostersPerPlayer"] < 1:
            fails.append(f"{scope.label}: rostersPerPlayer {r['rostersPerPlayer']!r}")
        return fails


class _FromLeague(MflLoader):
    """Reads mfl.league's raw file."""
    endpoint = "league"
    fetches = False
    element = ""      # 'divisions' -> divisions.division
    child = ""

    def parse(self, payload):
        lg = self._league_payload(payload)
        rows = api.as_list((lg.get(self.element) or {}).get(self.child))
        fields = sorted({k for r in rows for k in r})
        return fields, rows


class DivisionsLoader(_FromLeague):
    id = "mfl.divisions"
    history = True
    table = "core_mfl_divisions"
    element, child = "divisions", "division"

    def expected_fields(self):
        return []  # a league with one pool legitimately has no divisions

    def empty_is_valid(self, conn, scope):
        return _unit(conn, scope) == "LEAGUE"

    def checks(self, conn, scope):
        unit = _unit(conn, scope)
        fails = []
        n = conn.execute("SELECT COUNT(*) FROM core_mfl_divisions WHERE season = ? AND league_id = ?",
                         (scope.season, scope.league)).fetchone()[0]
        if unit in ("DIVISION", "CONFERENCE") and n < 2:
            fails.append(f"{scope.label}: pools are {unit}s but the league has {n} divisions")
        if unit == "CONFERENCE":
            bad = conn.execute("SELECT id FROM core_mfl_divisions WHERE season = ? AND league_id = ? AND conference IS NULL",
                               (scope.season, scope.league)).fetchall()
            if bad:
                fails.append(f"{scope.label}: divisions without a conference in a CONFERENCE-pool league: {[b[0] for b in bad]}")
        return fails


class ConferencesLoader(_FromLeague):
    id = "mfl.conferences"
    history = True
    table = "core_mfl_conferences"
    element, child = "conferences", "conference"

    def expected_fields(self):
        return []

    def empty_is_valid(self, conn, scope):
        return _unit(conn, scope) in ("LEAGUE", "DIVISION")

    def checks(self, conn, scope):
        if _unit(conn, scope) != "CONFERENCE":
            return []
        orphan = conn.execute("""SELECT d.id FROM core_mfl_divisions d WHERE d.season = ? AND d.league_id = ?
                                 AND NOT EXISTS (SELECT 1 FROM core_mfl_conferences c WHERE c.season = d.season
                                 AND c.league_id = d.league_id AND c.id = d.conference)""",
                              (scope.season, scope.league)).fetchall()
        return [f"{scope.label}: divisions name unknown conferences: {[o[0] for o in orphan]}"] if orphan else []


class FranchisesLoader(_FromLeague):
    id = "mfl.franchises"
    history = True
    table = "core_mfl_franchises"
    element, child = "franchises", "franchise"
    warn_new_fields = False   # contact fields (email, phone, address) deliberately not stored

    def checks(self, conn, scope):
        from .. import leagues
        fails = []
        q = (scope.season, scope.league)
        n = conn.execute("SELECT COUNT(*) FROM core_mfl_franchises WHERE season = ? AND league_id = ?", q).fetchone()[0]
        if n < 4:
            fails.append(f"{scope.label}: only {n} franchises")
        if _unit(conn, scope) in ("DIVISION", "CONFERENCE"):
            bad = conn.execute("""SELECT f.id FROM core_mfl_franchises f WHERE f.season = ? AND f.league_id = ?
                                  AND NOT EXISTS (SELECT 1 FROM core_mfl_divisions d WHERE d.season = f.season
                                  AND d.league_id = f.league_id AND d.id = f.division)""", q).fetchall()
            if bad:
                fails.append(f"{scope.label}: franchises with no valid division (no pool): {[b[0] for b in bad]}")
        mine = next((lg.my_franchise for lg in leagues.for_platform("mfl") if lg.league_id == scope.league), None)
        if mine and not conn.execute("SELECT 1 FROM core_mfl_franchises WHERE season = ? AND league_id = ? AND id = ?",
                                     (*q, mine)).fetchone():
            fails.append(f"{scope.label}: my franchise {mine} (config/my_franchises.toml) is not in the league")
        return fails


def _unit(conn, scope):
    r = conn.execute("SELECT playerLimitUnit FROM core_mfl_league WHERE season = ? AND league_id = ?",
                     (scope.season, scope.league)).fetchone()
    return r[0] if r else None


# --------------------------------------------------------------- rosters ----
class RostersLoader(MflLoader):
    id = "mfl.rosters"
    table = "core_mfl_rosters"
    mfl_type = "rosters"
    grain = "league_snapshot"
    raw_retention = "daily"

    def raw_is_final(self, conn, partition):
        return False  # current state, always

    def parse(self, payload):
        rows = []
        for f in api.as_list(json.loads(payload)["rosters"].get("franchise")):
            for p in api.as_list(f.get("player")):
                rows.append({**p, "franchise_id": f["id"], "week": f.get("week")})
        fields = sorted({k for r in rows for k in r})
        return fields, rows

    def scope_where(self, scope):
        return "season = ? AND league_id = ? AND snapshot_at = ?", (scope.season, scope.league, scope.snapshot)

    def derive(self, row):
        return {"season": self.scope.season, "league_id": self.scope.league, "snapshot_at": self.scope.snapshot}

    def checks(self, conn, scope):
        where, params = self.scope_where(scope)
        fails = []
        odd = conn.execute(f"SELECT DISTINCT status FROM core_mfl_rosters WHERE {where}", params).fetchall()
        unknown = sorted({o[0] for o in odd} - set(ROSTER_STATUSES))
        if unknown:
            fails.append(f"{scope.label}: unknown roster status {unknown}")
        stray = conn.execute("""SELECT DISTINCT r.franchise_id FROM core_mfl_rosters r
                                WHERE r.season = ? AND r.league_id = ? AND r.snapshot_at = ?
                                AND NOT EXISTS (SELECT 1 FROM core_mfl_franchises f WHERE f.season = r.season
                                AND f.league_id = r.league_id AND f.id = r.franchise_id)""", params).fetchall()
        if stray:
            fails.append(f"{scope.label}: roster franchises not in core_mfl_franchises: {[s[0] for s in stray]}")
        fails += self._pool_capacity(conn, scope)
        return fails

    @staticmethod
    def _pool_capacity(conn, scope):
        """The pool model, proven on every load: within a pool (MFL's own
        playerLimitUnit), no player has more owners than rostersPerPlayer."""
        lg = conn.execute("SELECT playerLimitUnit, rostersPerPlayer FROM core_mfl_league WHERE season = ? AND league_id = ?",
                          (scope.season, scope.league)).fetchone()
        if lg is None:
            return [f"{scope.label}: no core_mfl_league row; the pool model is unknown"]
        pool_of = {}
        for f in conn.execute("""SELECT f.id, f.division, d.conference FROM core_mfl_franchises f
                                 LEFT JOIN core_mfl_divisions d ON d.season = f.season AND d.league_id = f.league_id AND d.id = f.division
                                 WHERE f.season = ? AND f.league_id = ?""", (scope.season, scope.league)):
            pool_of[f["id"]] = {"LEAGUE": "", "DIVISION": f["division"], "CONFERENCE": f["conference"]}[lg["playerLimitUnit"]]
        owners = defaultdict(set)
        for r in conn.execute("SELECT franchise_id, id FROM core_mfl_rosters WHERE season = ? AND league_id = ? AND snapshot_at = ?",
                              (scope.season, scope.league, scope.snapshot)):
            owners[(pool_of.get(r["franchise_id"]), r["id"])].add(r["franchise_id"])
        over = [(pool, pid, sorted(fs)) for (pool, pid), fs in owners.items() if len(fs) > lg["rostersPerPlayer"]]
        if over:
            return [f"{scope.label}: {len(over)} players exceed rostersPerPlayer={lg['rostersPerPlayer']} "
                    f"in a {lg['playerLimitUnit']} pool (pool model wrong?): {over[:5]}"]
        return []


# ----------------------------------------------------------------- rules ----
class RulesLoader(MflLoader):
    id = "mfl.rules"
    table = "core_mfl_rules"
    mfl_type = "rules"

    def parse(self, payload):
        rows = []
        for grp in api.as_list(json.loads(payload)["rules"].get("positionRules")):
            for rule in api.as_list(grp.get("rule")):
                rows.append({**{k: _text(v) for k, v in rule.items()}, "positions": grp.get("positions")})
        fields = sorted({k for r in rows for k in r})
        return fields, rows

    def checks(self, conn, scope):
        n = conn.execute("SELECT COUNT(*) FROM core_mfl_rules WHERE season = ? AND league_id = ?",
                         (scope.season, scope.league)).fetchone()[0]
        blank = conn.execute("SELECT COUNT(*) FROM core_mfl_rules WHERE season = ? AND league_id = ? AND (points IS NULL OR event = '')",
                             (scope.season, scope.league)).fetchone()[0]
        fails = [f"{scope.label}: only {n} scoring rules"] if n < 10 else []
        return fails + ([f"{scope.label}: {blank} rules without points/event"] if blank else [])


# ----------------------------------------------------------- playerScores ----
class PlayerScoresLoader(MflLoader):
    id = "mfl.player_scores"
    table = "core_mfl_player_scores"
    mfl_type = "playerScores"
    endpoint = "playerScores"
    grain = "league_week"
    season_types = ("REG",)   # MFL fantasy seasons end in the regular season (endWeek 17)
    # First live backfill (2026-09-26): at 1.1 s spacing MFL answered playerScores
    # with 429s after 3 calls and kept refusing through 5 backoffs. Heavier endpoint,
    # wider spacing.
    CALL_SPACING = 4.0

    def partition(self, scope):
        return f"{scope.season}/{scope.league}/{scope.season_type}{scope.week:02d}"

    def fetch(self, partition):
        season, league = self._split(partition)
        week = int(partition.rsplit("/", 1)[1][3:])
        saved, api.interval[0] = api.interval[0], max(api.interval[0], self.CALL_SPACING)
        try:
            return api.export(season, league, self.mfl_type, W=week)
        finally:
            api.interval[0] = saved

    def raw_is_final(self, conn, partition):
        season, _ = self._split(partition)
        st, week = partition.rsplit("/", 1)[1][:3], int(partition.rsplit("/", 1)[1][3:])
        games = conn.execute("SELECT gameday, gametime, result FROM core_schedule WHERE season = ? AND season_type = ? AND week = ?",
                             (season, st, week)).fetchall()
        if not games or any(g["result"] is None for g in games):
            return False
        last = max(eastern_to_utc(g["gameday"], g["gametime"]) for g in games)
        return utcnow() >= last + timedelta(hours=config.GAME_HOURS) + SCORES_SETTLE

    def last_week(self, conn, season, league):
        # Found on the first 2025 backfill: W=18 in a league whose endWeek is 17 returns
        # WEEK 17's scores (labelled 17). Weeks past endWeek are not requested.
        r = conn.execute("SELECT endWeek FROM core_mfl_league WHERE season = ? AND league_id = ?", (season, league)).fetchone()
        return r[0] if r and r[0] else None

    def parse(self, payload):
        rows = api.as_list(json.loads(payload)["playerScores"].get("playerScore"))
        return sorted({k for r in rows for k in r}), rows

    def scope_rows(self, rows, scope):
        wrong = {r.get("week") for r in rows} - {str(scope.week)}
        if wrong:  # MFL answers an out-of-range W with another week's scores
            raise ValueError(f"{scope.label}: MFL returned week(s) {sorted(wrong)} for W={scope.week}")
        return rows

    def scope_where(self, scope):
        return ("season = ? AND league_id = ? AND season_type = ? AND week = ?",
                (scope.season, scope.league, scope.season_type, scope.week))

    def derive(self, row):
        return {"season": self.scope.season, "league_id": self.scope.league, "season_type": self.scope.season_type}

    def checks(self, conn, scope):
        where, params = self.scope_where(scope)
        n, wrong_week = conn.execute(f"SELECT COUNT(*), SUM(week != ?) FROM core_mfl_player_scores WHERE {where}",
                                     (scope.week, *params)).fetchone()
        fails = [f"{scope.label}: only {n} scored players (MFL scores not posted yet?)"] if n < 100 else []
        return fails + ([f"{scope.label}: {wrong_week} rows for another week"] if wrong_week else [])


# --------------------------------------------------------------- players ----
class PlayersLoader(MflLoader):
    id = "mfl.players"
    table = "core_mfl_players"
    mfl_type = "players"
    endpoint = "players"
    mfl_params = {"DETAILS": 1}
    MIN_ROWS = 1000

    def parse(self, payload):
        rows = api.as_list(json.loads(payload)["players"].get("player"))
        return sorted({k for r in rows for k in r}), rows

    def checks(self, conn, scope):
        n = conn.execute("SELECT COUNT(*) FROM core_mfl_players WHERE season = ? AND league_id = ?",
                         (scope.season, scope.league)).fetchone()[0]
        return [] if n >= self.MIN_ROWS else [f"{scope.label}: only {n} players (truncated?)"]


# ---------------------------------------------------------- weeklyResults ----
class WeeklyResultsLoader(PlayerScoresLoader):
    """One fetch (TYPE=weeklyResults&W=) feeds two tables: this one (one row per franchise PER GAME)
    and mfl.lineups (player rows). Finality, partitions, endWeek and the heavy-endpoint spacing are
    playerScores', inherited. History seasons are read (closed seasons are final, cached forever)."""
    id = "mfl.weekly_results"
    table = "core_mfl_weekly_results"
    mfl_type = "weeklyResults"
    endpoint = "weeklyResults"
    history = True
    warn_new_fields = False   # lineup lists and per-season extras (comments, spread) are not stored here
    CALL_SPACING = 3.0
    MAX_ABS_SCORE = 5000.0

    @staticmethod
    def _games(payload: bytes):
        d = json.loads(payload)["weeklyResults"]
        out = []
        for m in api.as_list(d.get("matchup")):
            frs = api.as_list(m.get("franchise"))
            if len(frs) > 2:
                raise ValueError(f"a matchup with {len(frs)} franchises")
            out.append(frs)
        return d.get("week"), out

    def last_week(self, conn, season, league):
        # h2h = ALL (30590's sibling TWE 55757: everyone "plays" everyone) has no matchups to report.
        r = conn.execute("SELECT h2h FROM core_mfl_league WHERE season = ? AND league_id = ?", (season, league)).fetchone()
        if r and r[0] != "YES":
            return 0
        return super().last_week(conn, season, league)

    def empty_is_valid(self, conn, scope):
        """A fantasy PLAYOFF week after the bracket is decided has no matchups (seen live: 30590 2020 wk17,
        46276 and 60398 2025 wk18). Only after lastRegularSeasonWeek; an empty regular-season week is a failure."""
        r = conn.execute("SELECT lastRegularSeasonWeek FROM core_mfl_league WHERE season = ? AND league_id = ?",
                         (scope.season, scope.league)).fetchone()
        return bool(r and r[0] and scope.week > r[0])

    def parse(self, payload):
        week, games = self._games(payload)
        if not games:   # the source's own answer is "no games": nothing to contradict the contract
            return self.expected_fields(), []
        rows = []
        for frs in games:
            for f in frs:
                other = [o["id"] for o in frs if o is not f]
                rows.append({**{k: v for k, v in f.items() if k != "player"}, "week": week,
                             "opponent_id": other[0] if other else ""})
        return sorted({k for frs in games for f in frs for k in f}), rows

    def checks(self, conn, scope):
        q = (scope.season, scope.league, scope.week)
        rows = conn.execute("""SELECT id, opponent_id, score, result FROM core_mfl_weekly_results
                               WHERE season = ? AND league_id = ? AND week = ?""", q).fetchall()
        fails = []
        nulls = [r for r in rows if r["score"] is None]
        if nulls:
            fails.append(f"{scope.label}: {len(nulls)} rows without a score (an unplayed week reads result=T, no score)")
        by = {(r["id"], r["opponent_id"]): r for r in rows}
        scores = defaultdict(set)
        for r in rows:
            if r["score"] is None:
                continue
            scores[r["id"]].add(r["score"])
            if abs(r["score"]) > self.MAX_ABS_SCORE:
                fails.append(f"{scope.label}: franchise {r['id']} score {r['score']} outside +-{self.MAX_ABS_SCORE:g}")
            if r["opponent_id"] == "":
                continue
            rev = by.get((r["opponent_id"], r["id"]))
            if rev is None:
                fails.append(f"{scope.label}: {r['id']} vs {r['opponent_id']} has no mirror row")
            elif rev["score"] is not None:
                want = "W" if r["score"] > rev["score"] else "L" if r["score"] < rev["score"] else "T"
                if r["result"] != want:
                    fails.append(f"{scope.label}: {r['id']} vs {r['opponent_id']} result {r['result']!r} but scores say {want!r}")
        for fid, sc in scores.items():
            if len(sc) > 1:
                fails.append(f"{scope.label}: franchise {fid} has different scores in its games: {sorted(sc)}")
        known = {r[0] for r in conn.execute("SELECT id FROM core_mfl_franchises WHERE season = ? AND league_id = ?", q[:2])}
        if known:
            stray = sorted({r["id"] for r in rows} - known)
            if stray:
                fails.append(f"{scope.label}: franchises not in core_mfl_franchises: {stray}")
        return fails


class LineupsLoader(WeeklyResultsLoader):
    """Reads mfl.weekly_results' raw file: franchise.player[] -> one row per franchise-week-player."""
    id = "mfl.lineups"
    table = "core_mfl_lineups"
    fetches = False

    def parse(self, payload):
        week, games = self._games(payload)
        if not games:
            return self.expected_fields(), []
        rows, seen = [], {}
        for frs in games:
            for f in frs:
                ps = api.as_list(f.get("player"))
                sig = sorted((p["id"], p.get("status")) for p in ps)
                if f["id"] in seen:   # a franchise's games share one lineup; a difference is a source invariant
                    if seen[f["id"]] != sig:
                        raise ValueError(f"franchise {f['id']} has different lineups in its games")
                    continue
                seen[f["id"]] = sig
                listed = {x for x in (f.get("starters") or "").split(",") if x}
                if listed != {p["id"] for p in ps if p.get("status") == "starter"}:
                    raise ValueError(f"franchise {f['id']}: `starters` disagrees with the players marked starter")
                rows += [{**p, "franchise_id": f["id"], "week": week} for p in ps]
        return sorted({k for r in rows for k in r} - {"franchise_id", "week"}), rows

    def checks(self, conn, scope):
        q = (scope.season, scope.league, scope.week)
        fails = []
        # reconciliation with the franchise's own score: starters' scores + adjustment == score
        bad = conn.execute("""SELECT w.id, w.score, w.adj_score, s.total FROM
                (SELECT id, MAX(score) score, MAX(COALESCE(adj_score, 0)) adj_score FROM core_mfl_weekly_results
                 WHERE season = ? AND league_id = ? AND week = ? GROUP BY id) w
              JOIN (SELECT franchise_id, SUM(score) total FROM core_mfl_lineups
                    WHERE season = ? AND league_id = ? AND week = ? AND status = 'starter' GROUP BY franchise_id) s
                ON s.franchise_id = w.id
              WHERE ABS(s.total + w.adj_score - w.score) > 0.011""", q + q).fetchall()
        if bad:
            fails.append(f"{scope.label}: starters' scores do not add to the franchise score for {[tuple(b) for b in bad[:3]]}")
        have = conn.execute("SELECT COUNT(DISTINCT id) FROM core_mfl_weekly_results WHERE season = ? AND league_id = ? AND week = ?", q).fetchone()[0]
        got = conn.execute("SELECT COUNT(DISTINCT franchise_id) FROM core_mfl_lineups WHERE season = ? AND league_id = ? AND week = ?", q).fetchone()[0]
        if have and have != got:
            fails.append(f"{scope.label}: {have} franchises in weekly_results but {got} with a lineup")
        return fails


# ------------------------------------------------------- projectedScores ----
class ProjectedScoresLoader(MflLoader):
    """Snapshots of MFL's per-player weekly projections: one raw file per fetch (daily retention), one scope
    per raw file. Only the NEXT unplayed regular-season week is fetched, every run, because its projections
    move. A COMPLETED week is deliberately NOT fetched: the first live load showed that after the games MFL's
    list is a partial one (30590 wk3: 895 players vs 1,007 for unplayed wk4; 166 of 896 starters, scoring up
    to 91, had no projection), so a post-game fetch is not the pre-game projection. The mart uses, per week,
    the last snapshot taken before that week's first kickoff."""
    id = "mfl.projected_scores"
    table = "core_mfl_projected_scores"
    mfl_type = "projectedScores"
    endpoint = "projectedScores"
    grain = "league_snapshot"
    raw_retention = "daily"
    MIN_PLAYERS = 100
    MAX_ABS_SCORE = 1000.0
    MAX_BLANK = 0.05

    def partition(self, scope):
        return f"{scope.season}/{scope.league}/{scope.season_type}{scope.week:02d}"

    @staticmethod
    def _week_of(partition: str) -> int:
        return int(partition.rsplit("/", 1)[1][3:])

    def fetch(self, partition):
        season, league = self._split(partition)
        return api.export(season, league, self.mfl_type, W=self._week_of(partition))

    def raw_is_final(self, conn, partition):
        return False   # a current-state feed: there is no moment at which it stops changing in a way we can rely on

    def snapshot_bases(self, conn, season, league, fetching):
        if not fetching:   # every week that has a raw file
            weeks = {self._week_of(r.partition) for r in raw_records(self.source, self.endpoint, f"{season}/{league}")}
            return [Scope(season, "REG", w, league=league) for w in sorted(weeks)]
        if season != schedule.current_season(conn):
            return []
        done = {w for t, w in schedule.completed_weeks(conn, season) if t == "REG"}
        reg = [r[0] for r in conn.execute("SELECT DISTINCT week FROM core_schedule WHERE season = ? AND season_type = 'REG' "
                                          "ORDER BY week", (season,))]
        end = conn.execute("SELECT endWeek FROM core_mfl_league WHERE season = ? AND league_id = ?", (season, league)).fetchone()
        end = end[0] if end and end[0] else None   # W past endWeek answers another week (see playerScores)
        nxt = next((w for w in reg if w not in done and (end is None or w <= end)), None)
        return [Scope(season, "REG", nxt, league=league)] if nxt is not None else []

    def parse(self, payload):
        d = json.loads(payload)["projectedScores"]
        rows = [{**r, "week": d.get("week")} for r in api.as_list(d.get("playerScore"))]
        return sorted({k for r in rows for k in r} - {"week"}), rows

    def scope_rows(self, rows, scope):
        wrong = {r.get("week") for r in rows} - {str(scope.week)}
        if wrong:
            raise ValueError(f"{scope.label}: MFL returned week(s) {sorted(wrong)} for W={scope.week}")
        # Every live response ends with ONE placeholder {"id": "", "score": ""} (found on the first live load, 2026-10-03:
        # NOT NULL on id). It names nobody, so it is not a row; a blank id WITH a score would be, and is refused.
        keep = [r for r in rows if r.get("id") or r.get("score") not in ("", None)]
        if any(not r.get("id") for r in keep):
            raise ValueError(f"{scope.label}: a projection with a score but no player id")
        return keep

    def scope_where(self, scope):
        return ("season = ? AND league_id = ? AND week = ? AND snapshot_at = ?",
                (scope.season, scope.league, scope.week, scope.snapshot))

    def derive(self, row):
        return {"season": self.scope.season, "season_type": self.scope.season_type, "league_id": self.scope.league,
                "snapshot_at": self.scope.snapshot}

    def checks(self, conn, scope):
        where, params = self.scope_where(scope)
        n, blank, big, top = conn.execute(f"""SELECT COUNT(*), SUM(score IS NULL), SUM(ABS(score) > ?), MAX(score)
                                              FROM core_mfl_projected_scores WHERE {where}""", (self.MAX_ABS_SCORE, *params)).fetchone()
        fails = []
        if n < self.MIN_PLAYERS:
            fails.append(f"{scope.label}: only {n} projected players (not posted yet?)")
        if n and blank / n > self.MAX_BLANK:
            fails.append(f"{scope.label}: {blank} of {n} projections are blank")
        if big:
            fails.append(f"{scope.label}: {big} projections beyond +-{self.MAX_ABS_SCORE:g}")
        if n and (top or 0) <= 0:
            fails.append(f"{scope.label}: no positive projection at all")
        return fails


# ------------------------------------------------- upcoming games + lineups ----
class UpcomingGamesLoader(ProjectedScoresLoader):
    """Snapshots of weeklyResults for the NEXT UNPLAYED regular-season week: who plays whom and who is in each
    lineup before the games (the card's PREVIEW). Same weeks and the same 'a completed week is never fetched' rule
    as the projections. Its own raw endpoint (`weeklyResultsUpcoming`), NOT mfl.weekly_results' partitions: that
    loader keeps only 3 non-final files per partition and could prune the pre-kickoff snapshot. One fetch feeds
    this table and core_mfl_upcoming_lineups."""
    id = "mfl.upcoming_games"
    table = "core_mfl_upcoming_games"
    mfl_type = "weeklyResults"
    endpoint = "weeklyResultsUpcoming"
    CALL_SPACING = 3.0

    def fetch(self, partition):
        season, league = self._split(partition)
        saved, api.interval[0] = api.interval[0], max(api.interval[0], self.CALL_SPACING)
        try:
            return api.export(season, league, self.mfl_type, W=self._week_of(partition))
        finally:
            api.interval[0] = saved

    def snapshot_bases(self, conn, season, league, fetching):
        if fetching:   # a league without head-to-head has no pairings (TWE 55757: h2h = ALL)
            r = conn.execute("SELECT h2h FROM core_mfl_league WHERE season = ? AND league_id = ?", (season, league)).fetchone()
            if r and r[0] != "YES":
                return []
        return super().snapshot_bases(conn, season, league, fetching)

    def parse(self, payload):
        week, games = WeeklyResultsLoader._games(payload)
        if not games:
            return self.expected_fields(), []
        rows = []
        for frs in games:
            for f in frs:
                other = [o["id"] for o in frs if o is not f]
                rows.append({**{k: v for k, v in f.items() if k != "player"}, "week": week,
                             "opponent_id": other[0] if other else ""})
        return sorted({k for frs in games for f in frs for k in f}), rows

    def scope_rows(self, rows, scope):
        wrong = {r.get("week") for r in rows} - {str(scope.week)}
        if wrong:
            raise ValueError(f"{scope.label}: MFL returned week(s) {sorted(wrong)} for W={scope.week}")
        return rows

    warn_new_fields = False   # result/spread/score appear as the week is played; this table keeps only the pairing

    def checks(self, conn, scope):
        q = (scope.season, scope.league, scope.week, scope.snapshot)
        rows = conn.execute("""SELECT id, opponent_id FROM core_mfl_upcoming_games
                               WHERE season = ? AND league_id = ? AND week = ? AND snapshot_at = ?""", q).fetchall()
        fails = []
        pairs = {(r["id"], r["opponent_id"]) for r in rows}
        miss = [p for p in pairs if p[1] != "" and (p[1], p[0]) not in pairs]
        if miss:
            fails.append(f"{scope.label}: {len(miss)} games without a mirror row, e.g. {miss[:2]}")
        known = {r[0] for r in conn.execute("SELECT id FROM core_mfl_franchises WHERE season = ? AND league_id = ?", q[:2])}
        stray = sorted({r["id"] for r in rows} - known) if known else []
        if stray:
            fails.append(f"{scope.label}: franchises not in core_mfl_franchises: {stray}")
        if len(rows) < 2:
            fails.append(f"{scope.label}: only {len(rows)} game rows")
        return fails


class UpcomingLineupsLoader(UpcomingGamesLoader):
    """Reads mfl.upcoming_games' raw file: franchise.player[] (id, status) per franchise.

    A franchise WITHOUT a lineup is normal, not a failure: found by the Wednesday rehearsal on 2026-10-05, when MFL answered
    week 5 (two weeks ahead of the week in progress) with a lineup for only 2 of 30590's 32 franchises, and with none at all for
    57653. MFL fills a new week's lineups in as it becomes the current week. So this table holds the lineups that exist, an
    empty answer is valid (the source's own), and nothing is guessed for the rest: a game whose franchise has no lineup has no
    projected total, and the preview says so (fdb/matchup_weeks.py)."""
    id = "mfl.upcoming_lineups"
    table = "core_mfl_upcoming_lineups"
    fetches = False

    def empty_is_valid(self, conn, scope):
        return True

    def parse(self, payload):
        week, games = WeeklyResultsLoader._games(payload)
        rows, seen = [], {}
        for frs in games:
            for f in frs:
                ps = api.as_list(f.get("player"))
                sig = sorted((p["id"], p.get("status")) for p in ps)
                if f["id"] in seen:
                    if seen[f["id"]] != sig:
                        raise ValueError(f"franchise {f['id']} has different lineups in its games")
                    continue
                seen[f["id"]] = sig
                listed = {x for x in (f.get("starters") or "").split(",") if x}
                if listed != {p["id"] for p in ps if p.get("status") == "starter"}:
                    raise ValueError(f"franchise {f['id']}: `starters` disagrees with the players marked starter")
                rows += [{**p, "franchise_id": f["id"], "week": week} for p in ps]
        if not rows:   # no franchise has a lineup yet: nothing to contradict the contract
            return self.expected_fields(), []
        return sorted({k for r in rows for k in r} - {"franchise_id", "week"}), rows

    def checks(self, conn, scope):
        """Lineups may be missing for some franchises; they may not exist for a franchise that is not playing."""
        q = (scope.season, scope.league, scope.week, scope.snapshot)
        stray = conn.execute("""SELECT DISTINCT l.franchise_id FROM core_mfl_upcoming_lineups l
                                WHERE l.season = ? AND l.league_id = ? AND l.week = ? AND l.snapshot_at = ?
                                AND NOT EXISTS (SELECT 1 FROM core_mfl_upcoming_games g WHERE g.season = l.season AND g.league_id = l.league_id
                                AND g.week = l.week AND g.snapshot_at = l.snapshot_at AND g.id = l.franchise_id)""", q).fetchall()
        return [f"{scope.label}: lineups for franchises that are not in the pairings: {[r[0] for r in stray]}"] if stray else []


# ------------------------------------------------------------ liveScoring ----
class LiveScoresLoader(ProjectedScoresLoader):
    """Snapshots of MFL's liveScoring for the week IN PROGRESS (first kickoff passed, week not complete): each franchise's score
    so far. A current-state feed (no snapshot is final), spaced like the other heavy endpoints. A week not in progress fetches
    nothing, so the weekly job (Wednesday, after the week closed) does no work here. One fetch feeds this table and
    core_mfl_live_players."""
    id = "mfl.live_scores"
    table = "core_mfl_live_scores"
    mfl_type = "liveScoring"
    endpoint = "liveScoring"
    CALL_SPACING = 3.0
    MAX_ABS_SCORE = 5000.0

    def fetch(self, partition):
        season, league = self._split(partition)
        saved, api.interval[0] = api.interval[0], max(api.interval[0], self.CALL_SPACING)
        try:
            return api.export(season, league, self.mfl_type, W=self._week_of(partition))
        finally:
            api.interval[0] = saved

    def snapshot_bases(self, conn, season, league, fetching):
        if not fetching:   # every week that has a raw file
            return super().snapshot_bases(conn, season, league, fetching)
        if season != schedule.current_season(conn):
            return []
        r = conn.execute("SELECT h2h FROM core_mfl_league WHERE season = ? AND league_id = ?", (season, league)).fetchone()
        if r and r[0] != "YES":   # a league without head-to-head has no matchups to score
            return []
        done = {w for t, w in schedule.completed_weeks(conn, season) if t == "REG"}
        now = utcnow()
        kick = {}
        for g in conn.execute("SELECT week, gameday, gametime FROM core_schedule WHERE season = ? AND season_type = 'REG'", (season,)):
            k = eastern_to_utc(g["gameday"], g["gametime"])
            kick[g["week"]] = min(kick.get(g["week"], k), k)
        live = [w for w in sorted(kick) if w not in done and kick[w] <= now]
        return [Scope(season, "REG", live[0], league=league)] if live else []

    @staticmethod
    def _games(payload: bytes):
        d = json.loads(payload)["liveScoring"]
        out = []
        for m in api.as_list(d.get("matchup")):
            frs = api.as_list(m.get("franchise"))
            if len(frs) > 2:
                raise ValueError(f"a matchup with {len(frs)} franchises")
            out.append(frs)
        return d.get("week"), out

    def parse(self, payload):
        week, games = self._games(payload)
        if not games:
            return self.expected_fields(), []
        rows = []
        for frs in games:
            for f in frs:
                other = [o["id"] for o in frs if o is not f]
                rows.append({**{k: v for k, v in f.items() if k != "players"}, "week": week,
                             "opponent_id": other[0] if other else ""})
        return sorted({k for frs in games for f in frs for k in f} - {"players"}), rows

    def scope_rows(self, rows, scope):
        wrong = {r.get("week") for r in rows} - {str(scope.week)}
        if wrong:
            raise ValueError(f"{scope.label}: MFL returned week(s) {sorted(wrong)} for W={scope.week}")
        return rows

    def checks(self, conn, scope):
        q = (scope.season, scope.league, scope.week, scope.snapshot)
        rows = conn.execute("""SELECT id, opponent_id, score FROM core_mfl_live_scores
                               WHERE season = ? AND league_id = ? AND week = ? AND snapshot_at = ?""", q).fetchall()
        fails = []
        pairs = {(r["id"], r["opponent_id"]) for r in rows}
        miss = [p for p in pairs if p[1] != "" and (p[1], p[0]) not in pairs]
        if miss:
            fails.append(f"{scope.label}: {len(miss)} games without a mirror row, e.g. {miss[:2]}")
        big = [r["id"] for r in rows if abs(r["score"]) > self.MAX_ABS_SCORE]
        if big:
            fails.append(f"{scope.label}: scores beyond +-{self.MAX_ABS_SCORE:g} for {sorted(set(big))[:3]}")
        by = defaultdict(set)
        for r in rows:
            by[r["id"]].add(r["score"])
        diff = sorted(f for f, sc in by.items() if len(sc) > 1)
        if diff:
            fails.append(f"{scope.label}: a franchise has different scores in its games: {diff[:3]}")
        known = {r[0] for r in conn.execute("SELECT id FROM core_mfl_franchises WHERE season = ? AND league_id = ?", q[:2])}
        stray = sorted({r["id"] for r in rows} - known) if known else []
        if stray:
            fails.append(f"{scope.label}: franchises not in core_mfl_franchises: {stray}")
        if len(rows) < 2:
            fails.append(f"{scope.label}: only {len(rows)} game rows")
        return fails


class LivePlayersLoader(LiveScoresLoader):
    """Reads mfl.live_scores' raw file: franchise.players.player[] -> one row per franchise-player (a franchise's games share
    one lineup, so a difference between its games is a source invariant, as in mfl.lineups)."""
    id = "mfl.live_players"
    table = "core_mfl_live_players"
    fetches = False

    def parse(self, payload):
        week, games = self._games(payload)
        rows, seen = [], {}
        for frs in games:
            for f in frs:
                box = f.get("players")
                ps = api.as_list(box.get("player") if isinstance(box, dict) else box)
                sig = sorted((p["id"], p.get("status"), p.get("score")) for p in ps)
                if f["id"] in seen:
                    if seen[f["id"]] != sig:
                        raise ValueError(f"franchise {f['id']} has different live lineups in its games")
                    continue
                seen[f["id"]] = sig
                rows += [{**p, "franchise_id": f["id"], "week": week} for p in ps]
        if not rows:
            return self.expected_fields(), []
        return sorted({k for r in rows for k in r} - {"franchise_id", "week"}), rows

    def checks(self, conn, scope):
        """A franchise's live starters add up to its live score (MFL's own total, within rounding) or the feed is not what we think."""
        q = (scope.season, scope.league, scope.week, scope.snapshot)
        bad = conn.execute("""SELECT s.id, s.score, p.total FROM
                (SELECT id, MAX(score) score FROM core_mfl_live_scores WHERE season = ? AND league_id = ? AND week = ? AND snapshot_at = ?
                 GROUP BY id) s
              JOIN (SELECT franchise_id, SUM(score) total FROM core_mfl_live_players
                    WHERE season = ? AND league_id = ? AND week = ? AND snapshot_at = ? AND status = 'starter' GROUP BY franchise_id) p
                ON p.franchise_id = s.id WHERE ABS(p.total - s.score) > 0.02""", q + q).fetchall()
        return ([f"{scope.label}: live starters do not add to the live score for {[tuple(b) for b in bad[:3]]}"] if bad else [])


LOADERS = (LeagueLoader, DivisionsLoader, ConferencesLoader, FranchisesLoader, RostersLoader,
           RulesLoader, PlayerScoresLoader, PlayersLoader, WeeklyResultsLoader, LineupsLoader, ProjectedScoresLoader, UpcomingGamesLoader, UpcomingLineupsLoader,
           LiveScoresLoader, LivePlayersLoader)
