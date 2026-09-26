"""Source-ownership registry (registry/sources.toml)."""
import tomllib

from . import config


class OwnershipError(RuntimeError):
    pass


def load() -> list[dict]:
    with open(config.REGISTRY_PATH, "rb") as f:
        tables = tomllib.load(f).get("table", [])
    names = [t["name"] for t in tables]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise OwnershipError(f"tables registered more than once: {sorted(dupes)}")
    return tables


def owner_of(table: str) -> str:
    for t in load():
        if t["name"] == table:
            return t["owner"]
    raise OwnershipError(f"table {table!r} is not in registry/sources.toml")


def assert_owner(loader_id: str, table: str) -> None:
    owner = owner_of(table)
    if owner != loader_id:
        raise OwnershipError(f"{loader_id!r} may not write {table!r}: it is owned by {owner!r}")


def weekly_loaders() -> list[str]:
    seen, out = set(), []
    for t in load():
        if t.get("weekly") and t["owner"] not in seen:
            seen.add(t["owner"])
            out.append(t["owner"])
    return out


def owners(kind: str = "loader") -> list[str]:
    """Owners in registry order. kind='loader' (default) or 'builder'; 'schema' is never returned."""
    seen, out = set(), []
    for t in load():
        o = t["owner"]
        if o == "schema" or o in seen or t.get("kind", "loader") != kind:
            continue
        seen.add(o)
        out.append(o)
    return out
