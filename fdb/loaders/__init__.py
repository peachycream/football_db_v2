"""Loader registry: id -> class. Table ownership lives in registry/sources.toml."""
from .nflverse_schedules import ScheduleLoader

LOADERS = {cls.id: cls for cls in (ScheduleLoader,)}


def get(loader_id: str):
    try:
        return LOADERS[loader_id]()
    except KeyError:
        raise SystemExit(f"unknown loader {loader_id!r}; known: {sorted(LOADERS)}")
