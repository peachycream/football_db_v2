"""Builders: derived tables rebuilt wholly from core tables. id -> callable(conn) -> report dict."""
from . import identity


def _identity(conn):
    r = identity.build(conn, apply=True)
    r["summary"] = f"{r['players']} players, {r['player_ids']} ids, {r['quarantined']} quarantined"
    return r


BUILDERS = {"identity.build": _identity}
