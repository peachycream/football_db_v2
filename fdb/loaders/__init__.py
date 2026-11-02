"""Loader registry: id -> class. Table ownership lives in registry/sources.toml."""
from . import cfbd, ddff, ftn, ftnfantasy, injuries, mfl, pff, pff_ncaa, ras, sleeper
from .dp_playerids import DpPlayerIdsLoader
from .nflverse_draft import CombineLoader, DraftPicksLoader
from .nflverse_players import PlayersLoader
from .nflverse_rosters_weekly import RostersWeeklyLoader
from .nflverse_schedules import ScheduleLoader
from .nflverse_weekly import (FfOpportunityLoader, FtnChartingLoader, NgsPassingLoader, NgsReceivingLoader, NgsRushingLoader,
                              ParticipationLoader, PbpLoader, PlayerStatsLoader, SnapCountsLoader)

LOADERS = {cls.id: cls for cls in (ScheduleLoader, PlayersLoader, RostersWeeklyLoader, DpPlayerIdsLoader,
                                   PlayerStatsLoader, SnapCountsLoader, PbpLoader, ParticipationLoader, DraftPicksLoader, CombineLoader,
                                   NgsPassingLoader, NgsReceivingLoader, NgsRushingLoader, FfOpportunityLoader, FtnChartingLoader,
                                   *mfl.LOADERS, *sleeper.LOADERS, *pff.LOADERS, *ftn.LOADERS, *ddff.LOADERS, *ftnfantasy.LOADERS,
                                   *injuries.LOADERS, *cfbd.LOADERS, *pff_ncaa.LOADERS, *ras.LOADERS)}


def get(loader_id: str):
    try:
        return LOADERS[loader_id]()
    except KeyError:
        raise SystemExit(f"unknown loader {loader_id!r}; known: {sorted(LOADERS)}")
