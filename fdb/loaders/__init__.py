"""Loader registry: id -> class. Table ownership lives in registry/sources.toml."""
from .dp_playerids import DpPlayerIdsLoader
from .nflverse_players import PlayersLoader
from .nflverse_rosters_weekly import RostersWeeklyLoader
from .nflverse_schedules import ScheduleLoader

LOADERS = {cls.id: cls for cls in (ScheduleLoader, PlayersLoader, RostersWeeklyLoader, DpPlayerIdsLoader)}


def get(loader_id: str):
    try:
        return LOADERS[loader_id]()
    except KeyError:
        raise SystemExit(f"unknown loader {loader_id!r}; known: {sorted(LOADERS)}")
