"""Loader framework: the five-step contract (REBUILD_DESIGN §5).

    fetch -> validate_source -> load -> check -> idempotency

A loader describes a source. The framework decides everything that went wrong
in v1 when loaders decided it for themselves:
  * WHICH scopes are loaded  (schedule-driven; a loader cannot pick weeks)
  * WHETHER a raw file may be reused  (finality + emptiness)
  * WHICH table it may write  (ownership registry)
  * HOW rows are written  (delete scope + insert in one transaction; never
    INSERT OR REPLACE) and that post-write checks roll the write back.
"""
import json
import sqlite3
from dataclasses import dataclass

from . import config, raw, registry, schedule
from .db import columns, table_hash


class LoadRefused(RuntimeError):
    """The framework would not load this scope (not an error in the data)."""


@dataclass(frozen=True)
class Scope:
    season: int
    season_type: str | None = None
    week: int | None = None
    league: str | None = None      # fantasy loaders: the league dimension (Phase 3)
    snapshot: str | None = None    # league_snapshot grain: the raw file's fetch stamp

    @property
    def label(self) -> str:
        if self.season == 0:
            return "all"
        out = f"season={self.season}"
        if self.week is not None:
            out += f"/{self.season_type}/week={self.week}"
        if self.league is not None:
            out += f"/league={self.league}"
        if self.snapshot is not None:
            out += f"/snapshot={self.snapshot}"
        return out


class Loader:
    id: str = ""
    source: str = ""
    endpoint: str = ""
    table: str = ""
    grain: str = ""          # 'snapshot' | 'reference' | 'season' | 'week'
    ext: str = "json"
    season_range: tuple[int, int] | None = None   # e.g. (2016, 2025) when the source stops
    warn_new_fields: bool = True                  # False when the table deliberately keeps a subset
    fetches: bool = True          # False: reads the raw file another loader fetched (same source/endpoint)
    raw_retention: str = "keep3"  # non-final raw kept per partition: 'keep3' | 'daily' (newest per UTC day)
    season_types: tuple[str, ...] = ("REG", "POST")  # week grains: which schedule weeks are offered

    # Grains: 'snapshot' | 'reference' | 'season' | 'week' (nflverse), and the league
    # dimension added in Phase 3:
    #   'league'           one scope per (season, league) in config/my_franchises.toml
    #   'league_week'      (season, completed week, league)
    #   'league_snapshot'  (season, league, raw fetch stamp): every retained raw file
    #                      is its own scope, so history survives a delete-scope reload

    def prepare(self, conn: sqlite3.Connection) -> None:
        """Hook run at the start of every load (e.g. read the schedule for derive())."""

    # --- to implement ------------------------------------------------------
    def partition(self, scope: Scope) -> str: raise NotImplementedError
    def fetch(self, partition: str) -> tuple[bytes, dict]: raise NotImplementedError
    def parse(self, payload: bytes) -> tuple[list[str], list[dict]]:
        """-> (source field names, rows as dicts keyed by source field names)"""
        raise NotImplementedError
    def scope_rows(self, rows: list[dict], scope: Scope) -> list[dict]: raise NotImplementedError
    def scope_where(self, scope: Scope) -> tuple[str, tuple]: raise NotImplementedError
    def derive(self, row: dict) -> dict:
        """Framework columns added to a source row (e.g. season_type). Never renames."""
        return {}
    def raw_is_final(self, conn: sqlite3.Connection, partition: str) -> bool: raise NotImplementedError
    def checks(self, conn: sqlite3.Connection, scope: Scope) -> list[str]:
        """Post-write plausibility checks, run INSIDE the transaction. Return failures."""
        return []
    def last_week(self, conn: sqlite3.Connection, season: int, league: str) -> int | None:
        """league_week grain: the last week the SOURCE serves for this league, if it
        says so (MFL endWeek). Completed weeks after it are not offered."""
        return None
    def empty_is_valid(self, conn: sqlite3.Connection, scope: Scope) -> bool:
        """An empty scope is refused (it would wipe good rows). A loader may accept
        one ONLY where the source itself says empty is the truth (e.g. an MFL league
        whose pools are not conferences has no conferences)."""
        return False
    def reference_seasons(self, rows: list[dict]) -> list[int]:
        raise NotImplementedError  # reference grain only

    # --- contract ----------------------------------------------------------
    def expected_fields(self) -> list[str]:
        p = config.CONTRACTS_DIR / f"{self.id}.fields"
        return [l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")]


# ---------------------------------------------------------------- step 1 ----
def fetch(conn: sqlite3.Connection, loader: Loader, partition: str, refetch: bool = False) -> tuple[raw.RawRecord, bool]:
    """-> (record, fetched_now). Reuses the cached file only if it is final and non-empty."""
    cached = raw.latest(loader.source, loader.endpoint, partition)
    if not loader.fetches:  # a sibling loader owns the fetch; read what it wrote
        if cached is None:
            raise LoadRefused(f"{loader.id}: no raw {loader.source}/{loader.endpoint}/{partition}; its fetching loader runs first")
        return cached, False
    if raw.cache_usable(cached) and not refetch:
        return cached, False
    payload, params = loader.fetch(partition)
    fields, rows = loader.parse(payload)
    count = 0 if raw.is_effectively_empty(rows) else len(rows)
    is_final = loader.raw_is_final(conn, partition) if count else False
    rec = raw.write(loader.source, loader.endpoint, partition, payload, loader.ext, params, count, is_final,
                    retention=loader.raw_retention)
    index_raw(conn, [rec])
    return rec, True


def index_raw(conn: sqlite3.Connection, recs: list[raw.RawRecord]) -> None:
    for r in recs:
        conn.execute(
            "INSERT OR IGNORE INTO raw_fetch_log (path, source, endpoint, partition, fetched_at, sha256, row_count, is_final, params)"
            " VALUES (?,?,?,?,?,?,?,?,?)",  # OR IGNORE: the path is the identity of an immutable file
            (r.path, r.source, r.endpoint, r.partition, r.fetched_at, r.sha256, r.row_count, int(r.is_final),
             json.dumps(r.params, sort_keys=True)))


# ---------------------------------------------------------------- step 2 ----
def validate_source(loader: Loader, fields: list[str], table_cols: list[str] | None = None) -> tuple[list[str], list[str]]:
    """-> (missing, new). Missing fails the load; new is a warning. This is the
    check v1 lacked when a copied mapping read a field the API never sent.
    `new` = source fields the table has no column for (i.e. silently not stored)."""
    expected = loader.expected_fields()
    missing = [f for f in expected if f not in fields]
    known = set(expected) | set(table_cols or [])
    new = [f for f in fields if f not in known] if loader.warn_new_fields else []
    return missing, new


# ---------------------------------------------------------------- scopes ----
def scopes(conn: sqlite3.Connection, loader: Loader, seasons: list[int] | None = None) -> list[Scope]:
    """The framework's answer to "what may this loader load". `seasons` can only
    narrow it."""
    if loader.grain == "snapshot":
        # One whole-file scope; exists once its raw file does.
        return [Scope(0)] if raw.latest(loader.source, loader.endpoint, loader.partition(Scope(0))) else []
    if loader.grain in LEAGUE_GRAINS:
        return _league_scopes(conn, loader, seasons)
    if loader.grain == "reference":
        rec = raw.latest(loader.source, loader.endpoint, loader.partition(Scope(0)))
        if rec is None:
            return []
        _, rows = loader.parse(rec.read_bytes())
        found = [s for s in loader.reference_seasons(rows) if s >= config.FIRST_SEASON]
    else:
        found = [s for s in schedule.seasons_loaded(conn) if s >= config.FIRST_SEASON]
    if seasons:
        found = [s for s in found if s in seasons]
    if loader.season_range:
        lo, hi = loader.season_range
        found = [s for s in found if lo <= s <= hi]
    if loader.grain == "week":
        return [Scope(s, t, w) for s in found for (t, w) in schedule.completed_weeks(conn, s)]
    return [Scope(s) for s in found]


LEAGUE_GRAINS = ("league", "league_week", "league_snapshot")


def _league_scopes(conn, loader: Loader, seasons: list[int] | None) -> list[Scope]:
    """League scopes come from config/my_franchises.toml (which leagues, which
    seasons) intersected with the schedule (which seasons exist) - never from the
    loader. league_snapshot scopes are the raw files themselves."""
    from . import leagues
    known = set(schedule.seasons_loaded(conn))
    pairs = [(s, lg.league_id) for lg in leagues.for_platform(loader.source)
             for s in lg.seasons if s in known and (not seasons or s in seasons)]
    if loader.grain == "league":
        return [Scope(s, league=l) for s, l in pairs]
    if loader.grain == "league_week":
        out = []
        for s, l in pairs:
            last = loader.last_week(conn, s, l)
            out += [Scope(s, t, w, league=l) for (t, w) in schedule.completed_weeks(conn, s)
                    if t in loader.season_types and (last is None or w <= last)]
        return out
    out = []
    for s, l in pairs:
        for rec in raw.records(loader.source, loader.endpoint, loader.partition(Scope(s, league=l))):
            out.append(Scope(s, league=l, snapshot=rec.path.rsplit("/", 1)[1].split(".")[0]))
    return out


def fetch_partitions(conn, loader: Loader, seasons: list[int] | None = None) -> list[str]:
    """What `fetch` should request. For league_snapshot this is the current
    configured leagues (a snapshot scope only exists once its file does)."""
    if loader.grain in ("reference", "snapshot"):
        return ["all"]
    if loader.grain == "league_snapshot":
        from . import leagues
        cur = schedule.current_season(conn)
        want = seasons or ([cur] if cur else [])
        return sorted({loader.partition(Scope(s, league=lg.league_id)) for lg in leagues.for_platform(loader.source)
                       for s in lg.seasons if s in want})
    return sorted({loader.partition(s) for s in scopes(conn, loader, seasons)})


# ------------------------------------------------------------ steps 3-4 ----
def _cast(value, decl: str, col: str = ""):
    if value is None or value == "" or value == "NA":
        return None
    decl = (decl or "").upper()
    if "INT" in decl:
        try:
            f = float(value)
        except ValueError:
            raise ValueError(f"non-numeric {value!r} for INTEGER column {col}") from None
        if not f.is_integer():
            raise ValueError(f"non-integer {value!r} for INTEGER column {col}")  # never truncate silently
        return int(f)
    if "REAL" in decl:
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"non-numeric {value!r} for REAL column {col}") from None
    return str(value)


def load(conn: sqlite3.Connection, loader: Loader, scope: Scope, apply: bool = False) -> dict:
    registry.assert_owner(loader.id, loader.table)
    if loader.grain in ("week", "league_week") and not schedule.week_is_complete(conn, scope.season, scope.season_type, scope.week):
        raise LoadRefused(f"{scope.label} is not complete per the schedule; refusing to load a partial week")

    rec = raw_for(loader, scope)
    if rec is None:
        raise LoadRefused(f"no raw file for {loader.id} {scope.label}; run fetch first")
    loader.scope, loader.raw_rec = scope, rec   # derive() may need them (league id, snapshot stamp)
    loader.prepare(conn)
    memo = getattr(loader, "_parsed", None)
    result = {"loader": loader.id, "scope": scope.label, "raw": rec.path, "new_fields": [],
              "missing_fields": [], "rows": 0, "failures": [], "applied": False}
    try:  # a payload that breaks a source invariant is a load FAILURE naming it, not a crash
        if memo and memo[0] == (rec.path, rec.sha256):   # one season file serves ~22 week scopes
            fields, rows = memo[1]
        else:
            fields, rows = loader.parse(rec.read_bytes())
            loader._parsed = ((rec.path, rec.sha256), (fields, rows))
        missing, new = validate_source(loader, fields, columns(conn, loader.table))
        result.update(new_fields=new, missing_fields=missing)
        if missing:
            result["failures"].append(f"source is missing expected fields: {missing}")
            return result
        rows = loader.scope_rows(rows, scope)
    except ValueError as e:
        result["failures"].append(f"{type(e).__name__}: {e}")
        return result
    if raw.is_effectively_empty(rows) and not loader.empty_is_valid(conn, scope):
        result["failures"].append("scope is empty in the raw file; empty is never loaded")
        return result

    decl = {r[1]: r[2] for r in conn.execute(f"PRAGMA table_info({loader.table})")}
    cols = [c for c in columns(conn, loader.table) if c != "load_id"]
    where, params = loader.scope_where(scope)

    conn.execute("BEGIN")
    try:
        cur = conn.execute("INSERT INTO load_log (loader, scope, raw_path, raw_sha256, rows_in) VALUES (?,?,?,?,?)",
                           (loader.id, scope.label, rec.path, rec.sha256, len(rows)))
        load_id = cur.lastrowid
        conn.execute(f"DELETE FROM {loader.table} WHERE {where}", params)
        sql = f"INSERT INTO {loader.table} ({', '.join(cols)}, load_id) VALUES ({', '.join('?' * (len(cols) + 1))})"
        try:
            conn.executemany(sql, ([_cast(full.get(c), decl[c], c) for c in cols] + [load_id]
                                   for full in ({**r, **loader.derive(r)} for r in rows)))
        except (sqlite3.IntegrityError, ValueError) as e:  # duplicated key; a value that doesn't fit its type
            conn.execute("ROLLBACK")
            result["failures"].append(f"{type(e).__name__}: {e}")
            return result
        n = conn.execute(f"SELECT COUNT(*) FROM {loader.table} WHERE {where}", params).fetchone()[0]
        result["rows"] = n
        if n != len(rows):
            result["failures"].append(f"wrote {n} rows for {len(rows)} source rows")
        result["failures"].extend(loader.checks(conn, scope))
        if result["failures"] or not apply:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")
            result["applied"] = True
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def raw_for(loader: Loader, scope: Scope) -> raw.RawRecord | None:
    """The raw file a scope loads from: the latest in its partition, or for a
    league_snapshot scope, exactly the file the scope names."""
    part = loader.partition(scope)
    if scope.snapshot is None:
        return raw.latest(loader.source, loader.endpoint, part)
    for r in raw.records(loader.source, loader.endpoint, part):
        if r.path.rsplit("/", 1)[1].split(".")[0] == scope.snapshot:
            return r
    return None


def sync_snapshots(conn: sqlite3.Connection, loader: Loader) -> int:
    """Delete core rows of snapshots whose raw file retention has pruned, so the
    table always equals what a rebuild from raw would produce. -> rows deleted."""
    if loader.grain != "league_snapshot":
        return 0
    keep = {(s.season, s.league, s.snapshot) for s in scopes(conn, loader)}
    have = conn.execute(f"SELECT DISTINCT season, league_id, snapshot_at FROM {loader.table}").fetchall()
    gone = [tuple(h) for h in have if tuple(h) not in keep]
    n = 0
    conn.execute("BEGIN")
    for s, l, snap in gone:
        n += conn.execute(f"DELETE FROM {loader.table} WHERE season = ? AND league_id = ? AND snapshot_at = ?",
                          (s, l, snap)).rowcount
    conn.execute("COMMIT")
    return n


# ---------------------------------------------------------------- step 5 ----
def check_idempotent(conn: sqlite3.Connection, loader: Loader, scope: Scope) -> tuple[bool, str, str]:
    """Reload a scope from raw and compare content hashes. A re-run that changes rows fails."""
    where, params = loader.scope_where(scope)
    before = table_hash(conn, loader.table, f"WHERE {where}", params)
    res = load(conn, loader, scope, apply=True)
    if res["failures"]:
        return False, before, "load failed: " + "; ".join(res["failures"])
    after = table_hash(conn, loader.table, f"WHERE {where}", params)
    return before == after, before, after
