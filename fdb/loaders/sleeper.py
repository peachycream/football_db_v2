"""Sleeper loaders (Phase 3): league, users, roster snapshots, and /players/nfl.

Sleeper rolls a dynasty league to a NEW league id every season (the new league's
previous_league_id names the old one), so config/my_franchises.toml lists one id
per season and the league check refuses a payload for another season.
Sleeper scoring is deferred (REBUILD_DESIGN §10.3); scoring_settings are kept as JSON.
"""
import json

from .. import http
from ..loader import Loader, Scope

API = "https://api.sleeper.app/v1"


def _jsonify(row: dict) -> dict:
    """Nested values -> JSON text under their own name (a cast; the framework's
    TEXT cast would otherwise store a Python repr)."""
    return {k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()}


class SleeperLoader(Loader):
    source = "sleeper"
    ext = "json"
    grain = "league"
    path = ""   # appended to /league/<id>

    def partition(self, scope: Scope) -> str:
        return f"{scope.season}/{scope.league}"

    def fetch(self, partition):
        league = partition.split("/")[1]
        url = f"{API}/league/{league}{self.path}"
        return http.get(url), {"url": url}

    def raw_is_final(self, conn, partition):
        return False  # current-state feeds; v2 loads only the live season's league ids

    def scope_where(self, scope):
        return "season = ? AND league_id = ?", (scope.season, scope.league)

    def derive(self, row):
        return {"season": self.scope.season, "league_id": self.scope.league}

    def scope_rows(self, rows, scope):
        return rows


class LeagueLoader(SleeperLoader):
    id = "sleeper.league"
    table = "core_sleeper_league"
    endpoint = "league"
    warn_new_fields = False   # chat / last-message fields deliberately not stored

    def parse(self, payload):
        lg = json.loads(payload)
        if not lg:
            return [], []
        return list(lg), [_jsonify({**lg, "sleeper_season": lg.get("season")})]

    def scope_rows(self, rows, scope):
        # The payload's own season/league must be the scope's: a Sleeper id is one season.
        bad = [r for r in rows if str(r.get("league_id")) != scope.league or str(r.get("sleeper_season")) != str(scope.season)]
        if bad:
            r = bad[0]
            raise ValueError(f"{scope.label}: payload is league {r.get('league_id')} season {r.get('sleeper_season')}; "
                             f"fix config/my_franchises.toml (Sleeper rolls league ids yearly)")
        return rows


class UsersLoader(SleeperLoader):
    id = "sleeper.users"
    table = "core_sleeper_users"
    endpoint = "users"
    path = "/users"
    warn_new_fields = False   # per-user UI settings not stored

    def parse(self, payload):
        rows = [_jsonify(u) for u in json.loads(payload) or []]
        return sorted({k for r in rows for k in r}), rows

    def checks(self, conn, scope):
        n = conn.execute("SELECT COUNT(*) FROM core_sleeper_users WHERE season = ? AND league_id = ?",
                         (scope.season, scope.league)).fetchone()[0]
        return [] if n >= 2 else [f"{scope.label}: only {n} users"]


class RostersLoader(SleeperLoader):
    id = "sleeper.rosters"
    table = "core_sleeper_rosters"
    endpoint = "rosters"
    path = "/rosters"
    grain = "league_snapshot"
    raw_retention = "daily"
    warn_new_fields = False   # roster-level settings/metadata (W-L, nicknames) not stored

    def parse(self, payload):
        rosters = json.loads(payload) or []
        fields = sorted({k for r in rosters for k in r})
        rows = []
        for r in rosters:
            starters, taxi, reserve = (set(r.get(k) or []) for k in ("starters", "taxi", "reserve"))
            for pid in r.get("players") or []:
                rows.append({"roster_id": r["roster_id"], "owner_id": r.get("owner_id"),
                             "co_owners": json.dumps(r["co_owners"]) if r.get("co_owners") else None,
                             "player_id": pid, "in_starters": int(pid in starters),
                             "in_taxi": int(pid in taxi), "in_reserve": int(pid in reserve)})
            # Verified live 2026-09-26: starters/taxi/reserve are subsets of players.
            # If Sleeper ever breaks that, the id would be silently dropped - refuse.
            stray = (starters - {"0"} | taxi | reserve) - set(r.get("players") or [])
            if stray:
                raise ValueError(f"roster {r['roster_id']}: ids in starters/taxi/reserve but not players: {sorted(stray)}")
        self._n_rosters = len(rosters)
        return fields, rows

    def scope_where(self, scope):
        return "season = ? AND league_id = ? AND snapshot_at = ?", (scope.season, scope.league, scope.snapshot)

    def derive(self, row):
        return {"season": self.scope.season, "league_id": self.scope.league, "snapshot_at": self.scope.snapshot}

    def checks(self, conn, scope):
        where, params = self.scope_where(scope)
        n = conn.execute(f"SELECT COUNT(DISTINCT roster_id) FROM core_sleeper_rosters WHERE {where}", params).fetchone()[0]
        total = conn.execute("SELECT total_rosters FROM core_sleeper_league WHERE season = ? AND league_id = ?",
                             (scope.season, scope.league)).fetchone()
        fails = []
        if total and n != total[0]:
            fails.append(f"{scope.label}: {n} rosters with players, league has {total[0]} (an empty roster?)")
        dup = conn.execute(f"SELECT player_id, COUNT(*) FROM core_sleeper_rosters WHERE {where} "
                           "GROUP BY player_id HAVING COUNT(*) > 1", params).fetchall()
        if dup:  # single pool, one owner per player
            fails.append(f"{scope.label}: players on two rosters: {[d[0] for d in dup][:5]}")
        return fails


class PlayersLoader(SleeperLoader):
    """/players/nfl: ~15 MB. Sleeper asks for at most one call per day."""
    id = "sleeper.players"
    table = "core_sleeper_players"
    endpoint = "players_nfl"
    grain = "snapshot"
    warn_new_fields = False   # identity/bio subset; news, injury notes, odds ids not stored
    MIN_ROWS = 10000

    def partition(self, scope):
        return "all"

    def fetch(self, partition):
        url = f"{API}/players/nfl"
        return http.get(url), {"url": url}

    def parse(self, payload):
        data = json.loads(payload) or {}
        rows = []
        for key, p in data.items():
            if str(p.get("player_id")) != key:
                raise ValueError(f"players/nfl key {key} holds player_id {p.get('player_id')}")
            rows.append(_jsonify(p))
        return sorted({k for r in rows for k in r}), rows

    def scope_where(self, scope):
        return "1 = 1", ()

    def derive(self, row):
        return {}

    def checks(self, conn, scope):
        n = conn.execute("SELECT COUNT(*) FROM core_sleeper_players").fetchone()[0]
        fails = [] if n >= self.MIN_ROWS else [f"only {n} players; expected {self.MIN_ROWS:,}+ (truncated?)"]
        dup = conn.execute("""SELECT TRIM(gsis_id) g, COUNT(*) FROM core_sleeper_players WHERE TRIM(gsis_id) != ''
                              GROUP BY g HAVING COUNT(*) > 1""").fetchall()
        # Reported, not failed: identity.py refuses both claims of a shared gsis_id.
        self.shared_gsis = [d[0] for d in dup]
        return fails


LOADERS = (LeagueLoader, UsersLoader, RostersLoader, PlayersLoader)
