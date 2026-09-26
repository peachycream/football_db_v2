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

    @property
    def label(self) -> str:
        if self.week is None:
            return f"season={self.season}"
        return f"season={self.season}/{self.season_type}/week={self.week}"


class Loader:
    id: str = ""
    source: str = ""
    endpoint: str = ""
    table: str = ""
    grain: str = ""          # 'reference' | 'season' | 'week'
    ext: str = "json"

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
    if raw.cache_usable(cached) and not refetch:
        return cached, False
    payload, params = loader.fetch(partition)
    fields, rows = loader.parse(payload)
    count = 0 if raw.is_effectively_empty(rows) else len(rows)
    is_final = loader.raw_is_final(conn, partition) if count else False
    rec = raw.write(loader.source, loader.endpoint, partition, payload, loader.ext, params, count, is_final)
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
def validate_source(loader: Loader, fields: list[str]) -> tuple[list[str], list[str]]:
    """-> (missing, new). Missing fails the load; new is a warning. This is the
    check v1 lacked when a copied mapping read a field the API never sent."""
    expected = loader.expected_fields()
    missing = [f for f in expected if f not in fields]
    new = [f for f in fields if f not in expected]
    return missing, new


# ---------------------------------------------------------------- scopes ----
def scopes(conn: sqlite3.Connection, loader: Loader, seasons: list[int] | None = None) -> list[Scope]:
    """The framework's answer to "what may this loader load". `seasons` can only
    narrow it."""
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
    if loader.grain == "week":
        return [Scope(s, t, w) for s in found for (t, w) in schedule.completed_weeks(conn, s)]
    return [Scope(s) for s in found]


# ------------------------------------------------------------ steps 3-4 ----
def _cast(value, decl: str):
    if value is None or value == "" or value == "NA":
        return None
    decl = (decl or "").upper()
    if "INT" in decl:
        f = float(value)
        if not f.is_integer():
            raise ValueError(f"non-integer {value!r} for INTEGER column")  # never truncate silently
        return int(f)
    if "REAL" in decl:
        return float(value)
    return str(value)


def load(conn: sqlite3.Connection, loader: Loader, scope: Scope, apply: bool = False) -> dict:
    registry.assert_owner(loader.id, loader.table)
    if loader.grain == "week" and not schedule.week_is_complete(conn, scope.season, scope.season_type, scope.week):
        raise LoadRefused(f"{scope.label} is not complete per the schedule; refusing to load a partial week")

    rec = raw.latest(loader.source, loader.endpoint, loader.partition(scope))
    if rec is None:
        raise LoadRefused(f"no raw file for {loader.id} {scope.label}; run fetch first")
    fields, rows = loader.parse(rec.read_bytes())
    missing, new = validate_source(loader, fields)
    result = {"loader": loader.id, "scope": scope.label, "raw": rec.path, "new_fields": new,
              "missing_fields": missing, "rows": 0, "failures": [], "applied": False}
    if missing:
        result["failures"].append(f"source is missing expected fields: {missing}")
        return result

    rows = loader.scope_rows(rows, scope)
    if raw.is_effectively_empty(rows):
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
        for r in rows:
            full = {**r, **loader.derive(r)}
            conn.execute(sql, [_cast(full.get(c), decl[c]) for c in cols] + [load_id])
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
