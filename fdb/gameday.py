"""Kickoff windows for the player-status alerts (Phase 13).

Calibrated on the Week 4 Sunday slate of 2026-10-04 (28 teams measured, scratch probe in REBUILD_LOG Phase 13): ESPN's
active/inactive entries first appear 70-89 minutes before kickoff (one outlier at 245) and keep arriving until about
17-20 minutes before. So a game's window opens LEAD = 120 minutes before kickoff (margin over the 89) and the engine
sends its "final check" once the game is FINAL_AT = 15 minutes out.

Games come from core_schedule (nflverse; gametime is US Eastern, converted by timeutil.eastern_to_utc) and teams are
the canonical `team_aliases.team`, so ESPN's WSH/LAR and nflverse's WAS/LA meet on one name."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .timeutil import eastern_to_utc

LEAD = timedelta(minutes=120)
FINAL_AT = timedelta(minutes=15)


@dataclass(frozen=True)
class Game:
    game_id: str
    season_type: str
    week: int
    kickoff: datetime          # UTC
    gametime_et: str           # 'HH:MM' as the schedule has it
    home: str                  # canonical team
    away: str

    def opponent(self, team: str) -> str:
        return self.away if team == self.home else self.home

    def when(self, team: str) -> str:
        """'4:25 PM ET vs SEA' from `team`'s point of view."""
        h, m = (int(x) for x in (self.gametime_et or "13:00").split(":")[:2])
        return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'} ET {'vs' if team == self.home else '@'} {self.opponent(team)}"


def games(conn, season: int, season_type: str, week: int) -> list[Game]:
    rows = conn.execute("""SELECT s.game_id, s.gameday, s.gametime, ah.team AS home, aa.team AS away
                           FROM core_schedule s
                           JOIN team_aliases ah ON ah.abbr = s.home_team AND s.season BETWEEN ah.season_from AND ah.season_to
                           JOIN team_aliases aa ON aa.abbr = s.away_team AND s.season BETWEEN aa.season_from AND aa.season_to
                           WHERE s.season = ? AND s.season_type = ? AND s.week = ?
                           ORDER BY s.gameday, s.gametime, s.game_id""", (season, season_type, week)).fetchall()
    return [Game(r["game_id"], season_type, week, eastern_to_utc(r["gameday"], r["gametime"]), r["gametime"] or "13:00",
                 r["home"], r["away"]) for r in rows]


def by_team(gs: list[Game]) -> dict[str, Game]:
    out = {}
    for g in gs:
        out[g.home] = g
        out[g.away] = g
    return out


def is_open(g: Game, now: datetime) -> bool:
    """The polling window: LEAD before kickoff until kickoff."""
    return g.kickoff - LEAD <= now < g.kickoff


def open_games(gs: list[Game], now: datetime) -> list[Game]:
    return [g for g in gs if is_open(g, now)]


def next_open(gs: list[Game], now: datetime) -> datetime | None:
    """When the next window opens (None if no later game)."""
    later = [g.kickoff - LEAD for g in gs if g.kickoff - LEAD > now]
    return min(later) if later else None


def minutes_to(g: Game, now: datetime) -> float:
    return (g.kickoff - now).total_seconds() / 60
