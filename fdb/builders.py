"""Builders: derived tables rebuilt wholly from core tables. id -> callable(conn) -> report dict."""
from . import dashboard, devy, env, fantasy, identity, idp_cfbd, idp_model, idp_prospect, matchup, participation, trinity


def _identity(conn):
    r = identity.build(conn, apply=True)
    r["summary"] = f"{r['players']} players, {r['player_ids']} ids, {r['quarantined']} quarantined"
    return r


BUILDERS = {"identity.build": _identity, "fantasy.config": fantasy.build, "participation.seam": participation.build, "env.build": env.build,
            "dashboard.build": dashboard.build,
            "idp_model.build": idp_model.build, "idp_prospect.outcomes": idp_prospect.build, "idp_prospect.cfbd_bridge": idp_cfbd.build_bridge, "idp_prospect.features": idp_prospect.build_features, "trinity.build": trinity.build, "matchup.build": matchup.build, "devy.identity": devy.build}
