"""MyFantasyLeague loaders (Phase 3). Client and live-verified source facts: fdb/mfl.py.

One TYPE=league fetch feeds four tables: mfl.league fetches it; mfl.divisions,
mfl.conferences and mfl.franchises read the same raw file (`fetches = False`),
so MFL is called once per league, not four times.
"""
import json
from collections import defaultdict
from datetime import timedelta

from .. import config, mfl as api, schedule
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


LOADERS = (LeagueLoader, DivisionsLoader, ConferencesLoader, FranchisesLoader, RostersLoader,
           RulesLoader, PlayerScoresLoader, PlayersLoader)
