"""SQLite connection, schema migrations and content hashing."""
import hashlib
import sqlite3
from pathlib import Path

from . import config

# Framework bookkeeping: excluded from content hashes because it records WHEN
# things happened, not WHAT the data is.
META_TABLES = {"schema_migrations", "raw_fetch_log", "load_log"}
META_COLUMNS = {"load_id"}


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # explicit BEGIN/COMMIT only
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for f in sorted(config.SCHEMA_DIR.glob("*.sql")):
        if f.name in done:
            continue
        conn.execute("BEGIN")
        try:
            for stmt in _split_sql(f.read_text()):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (f.name,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(f.name)
    return applied


def _split_sql(text: str) -> list[str]:
    """Split a schema file on ';' at line end. Schema files must not put ';'
    inside string literals at a line end (none do)."""
    stmts, buf = [], []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            s = "\n".join(buf).strip()
            if s.rstrip(";").strip():
                stmts.append(s)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def data_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [r[0] for r in rows if r[0] not in META_TABLES]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def table_hash(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> str:
    cols = [c for c in columns(conn, table) if c not in META_COLUMNS]
    sql = f"SELECT {', '.join(cols)} FROM {table} {where}"
    rows = sorted(repr(tuple(r)) for r in conn.execute(sql, params))
    h = hashlib.sha256()
    h.update(repr(cols).encode())
    for r in rows:
        h.update(r.encode())
    return h.hexdigest()


def content_hash(conn: sqlite3.Connection) -> str:
    """Hash of every data table's content, independent of load order/timestamps."""
    h = hashlib.sha256()
    for t in data_tables(conn):
        h.update(t.encode())
        h.update(table_hash(conn, t).encode())
    return h.hexdigest()
