"""Immutable raw store (REBUILD_DESIGN §2.2, §5.1).

Every fetch is written exactly as received to
    data/raw/<source>/<endpoint>/<partition>/<stamp>.<ext>
with a sidecar <stamp>.<ext>.meta.json holding the manifest. The sidecars, not
the database, are the durable manifest: the database is disposable, so
`raw_fetch_log` is rebuilt from them.

Cache rule (hard-won in v1, rule 14): a raw file may be REUSED instead of
re-fetched only if it is final AND not effectively empty. Finality is decided
by the framework at fetch time, never by the loader's caller.
"""
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config
from .timeutil import stamp, utcnow


@dataclass(frozen=True)
class RawRecord:
    source: str
    endpoint: str
    partition: str
    path: str          # relative to RAW_DIR, forward slashes
    fetched_at: str    # ISO UTC
    sha256: str
    row_count: int
    is_final: bool
    params: dict

    def full_path(self) -> Path:
        return config.RAW_DIR / self.path

    def read_bytes(self) -> bytes:
        return self.full_path().read_bytes()


def is_effectively_empty(obj) -> bool:
    """True for None, '', and containers whose every member is effectively empty.

    Must recurse: PFF wraps list payloads in dicts, so {"coverage_scheme": []}
    has len 1 and a len()==0 check passes it as data (v1 hard rule 14)."""
    if obj is None:
        return True
    if isinstance(obj, (str, bytes)):
        return len(obj.strip()) == 0
    if isinstance(obj, dict):
        return all(is_effectively_empty(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(is_effectively_empty(v) for v in obj)
    return False  # numbers, bools: a value is a value, including 0


def _partition_dir(source: str, endpoint: str, partition: str) -> Path:
    return config.RAW_DIR / source / endpoint / partition


def write(source: str, endpoint: str, partition: str, payload: bytes, ext: str,
          params: dict, row_count: int, is_final: bool, retention: str = "keep3") -> RawRecord:
    now = utcnow()
    d = _partition_dir(source, endpoint, partition)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{stamp(now)}.{ext}"
    target = d / name
    if target.exists():
        raise FileExistsError(target)  # raw is immutable; never overwrite
    target.write_bytes(payload)
    rec = RawRecord(
        source=source, endpoint=endpoint, partition=partition,
        path=target.relative_to(config.RAW_DIR).as_posix(),
        fetched_at=now.isoformat(), sha256=hashlib.sha256(payload).hexdigest(),
        row_count=row_count, is_final=is_final, params=params,
    )
    Path(str(target) + ".meta.json").write_text(json.dumps(asdict(rec), indent=2, sort_keys=True))
    prune(source, endpoint, partition, retention)
    return rec


KEEP_NON_FINAL = 3


def prune(source: str, endpoint: str, partition: str, retention: str = "keep3") -> list[str]:
    """Current-state feeds are re-fetched every run and never final, so superseded
    snapshots would pile up (~15 MB a week). A FINAL file is never deleted, and
    nothing is ever modified in place. Policies for NON-final files:
      keep3  the newest KEEP_NON_FINAL per partition (feeds whose history is worthless)
      daily  the newest file of each UTC day, every day kept (roster snapshots: the
             history IS the data, and one per day bounds it at ~1.5 MB/day for 8 leagues)"""
    non_final = [r for r in records(source, endpoint, partition) if not r.is_final]
    if retention == "daily":
        newest = {}
        for r in non_final:  # sorted by fetched_at, so the last one per day wins
            newest[r.fetched_at[:10]] = r
        doomed = [r for r in non_final if newest[r.fetched_at[:10]] is not r]
    elif retention == "keep3":
        doomed = non_final[:-KEEP_NON_FINAL]
    else:
        raise ValueError(f"unknown raw retention policy {retention!r}")
    gone = []
    for r in doomed:
        p = r.full_path()
        p.unlink(missing_ok=True)
        Path(str(p) + ".meta.json").unlink(missing_ok=True)
        gone.append(r.path)
    return gone


def _load_meta(p: Path) -> RawRecord:
    return RawRecord(**json.loads(p.read_text()))


def records(source: str | None = None, endpoint: str | None = None,
            partition: str | None = None) -> list[RawRecord]:
    base = config.RAW_DIR
    if source:
        base = base / source
        if endpoint:
            base = base / endpoint
            if partition:
                base = base / partition
    if not base.exists():
        return []
    out = [_load_meta(p) for p in base.rglob("*.meta.json")]
    out.sort(key=lambda r: (r.source, r.endpoint, r.partition, r.fetched_at))
    return out


def latest(source: str, endpoint: str, partition: str) -> RawRecord | None:
    recs = records(source, endpoint, partition)
    return recs[-1] if recs else None


def cache_usable(rec: RawRecord | None) -> bool:
    """A non-final or empty raw file is never served from cache."""
    return rec is not None and rec.is_final and rec.row_count > 0
