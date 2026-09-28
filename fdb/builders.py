"""Builders: derived tables rebuilt wholly from core tables. id -> callable(conn) -> report dict."""
from . import dashboard, env, fantasy, identity, participation


def _identity(conn):
    r = identity.build(conn, apply=True)
    r["summary"] = f"{r['players']} players, {r['player_ids']} ids, {r['quarantined']} quarantined"
    return r


BUILDERS = {"identity.build": _identity, "fantasy.config": fantasy.build, "participation.seam": participation.build, "env.build": env.build,
            "dashboard.build": dashboard.build}
