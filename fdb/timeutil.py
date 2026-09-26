"""Time helpers. Stdlib only, and no zoneinfo: Windows Python has no tz database
without the tzdata package, so US Eastern is computed from the DST rule directly."""
import os
from datetime import date, datetime, time, timedelta, timezone


def utcnow() -> datetime:
    """Current UTC time. FDB_NOW (ISO 8601, UTC) overrides it for tests and replays."""
    override = os.environ.get("FDB_NOW")
    if override:
        return parse_utc(override)
    return datetime.now(timezone.utc)


def parse_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def stamp(dt: datetime) -> str:
    """Filesystem-safe UTC stamp (no colons, valid on Windows)."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def eastern_to_utc(day: str, hhmm: str) -> datetime:
    """nflverse gameday ('YYYY-MM-DD') + gametime ('HH:MM', US Eastern) -> UTC.
    DST since 2007: second Sunday of March 02:00 to first Sunday of November 02:00."""
    d = date.fromisoformat(day)
    h, m = (int(x) for x in (hhmm or "13:00").split(":")[:2])
    local = datetime.combine(d, time(h, m))
    dst_start = datetime.combine(_nth_sunday(d.year, 3, 2), time(2))
    dst_end = datetime.combine(_nth_sunday(d.year, 11, 1), time(2))
    offset = 4 if dst_start <= local < dst_end else 5
    return (local + timedelta(hours=offset)).replace(tzinfo=timezone.utc)
