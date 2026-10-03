"""config/my_franchises.toml: which fantasy leagues v2 loads, for which seasons,
and which franchise in each is mine. The loaders' league scopes come from here."""
import tomllib
from dataclasses import dataclass

from . import config

PATH = config.ROOT / "config" / "my_franchises.toml"
PLATFORMS = ("mfl", "sleeper")


@dataclass(frozen=True)
class League:
    platform: str
    league_id: str
    name: str
    my_franchise: str
    seasons: tuple[int, ...]
    history_seasons: tuple[int, ...] = ()   # EXTRA closed seasons, read only by loaders with `history = True`


def load() -> list[League]:
    with open(PATH, "rb") as f:
        rows = tomllib.load(f).get("league", [])
    out, seen = [], set()
    for r in rows:
        lg = League(r["platform"], str(r["league_id"]), r["name"], str(r["my_franchise"]),
                    tuple(int(s) for s in r["seasons"]),
                    tuple(int(s) for s in r.get("history_seasons", ())))
        if lg.platform not in PLATFORMS:
            raise ValueError(f"{PATH.name}: unknown platform {lg.platform!r}")
        if (lg.platform, lg.league_id) in seen:
            raise ValueError(f"{PATH.name}: league {lg.platform}:{lg.league_id} listed twice")
        seen.add((lg.platform, lg.league_id))
        out.append(lg)
    return out


def for_platform(platform: str) -> list[League]:
    return [lg for lg in load() if lg.platform == platform]
