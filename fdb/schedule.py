"""Completeness gate (REBUILD_DESIGN §5.3). The schedule decides what may be loaded.

A game is final when it has a result AND GAME_HOURS + SETTLE_HOURS have passed
since kickoff. A week is complete when every scheduled game in it is final. The
result column is required as well as the clock, so a postponed game (no result)
holds its week open however much time has passed.

This is deliberately two conditions, not one. v1's gate asked only "is a game
in progress", which passed on a Friday with 15 of 16 games unplayed.
"""
import sqlite3
from datetime import datetime, timedelta

from . import config
from .timeutil import eastern_to_utc, utcnow

SETTLE = timedelta(hours=config.GAME_HOURS + config.SETTLE_HOURS)


def _game_final(row, now: datetime) -> bool:
    if row["result"] is None:
        return False
    return now >= eastern_to_utc(row["gameday"], row["gametime"]) + SETTLE


def completed_weeks(conn: sqlite3.Connection, season: int, now: datetime | None = None) -> list[tuple[str, int]]:
    """[(season_type, week), ...] whose every game is final, in play order."""
    now = now or utcnow()
    rows = conn.execute(
        "SELECT season_type, week, gameday, gametime, result FROM core_schedule WHERE season = ?", (season,)
    ).fetchall()
    weeks: dict[tuple[str, int], bool] = {}
    for r in rows:
        key = (r["season_type"], r["week"])
        weeks[key] = weeks.get(key, True) and _game_final(r, now)
    order = {"REG": 0, "POST": 1}
    return sorted((k for k, ok in weeks.items() if ok), key=lambda k: (order[k[0]], k[1]))


def week_is_complete(conn, season: int, season_type: str, week: int, now: datetime | None = None) -> bool:
    return (season_type, week) in completed_weeks(conn, season, now)


def season_is_closed(conn: sqlite3.Connection, season: int, now: datetime | None = None) -> bool:
    """Closed = the Super Bowl exists in the schedule and is final. Before the
    playoff games are scheduled the SB row does not exist, so an in-progress
    season can never read as closed."""
    now = now or utcnow()
    sb = conn.execute(
        "SELECT gameday, gametime, result FROM core_schedule WHERE season = ? AND game_type = 'SB'", (season,)
    ).fetchall()
    return bool(sb) and all(_game_final(r, now) for r in sb)


def seasons_loaded(conn) -> list[int]:
    return [r[0] for r in conn.execute("SELECT DISTINCT season FROM core_schedule ORDER BY season")]


def current_season(conn, now: datetime | None = None) -> int | None:
    """The latest season whose first game has kicked off; else the latest closed one."""
    now = now or utcnow()
    best = None
    for s in seasons_loaded(conn):
        first = conn.execute("SELECT MIN(gameday) FROM core_schedule WHERE season = ?", (s,)).fetchone()[0]
        if first and eastern_to_utc(first, "00:00") <= now:
            best = s
    return best
