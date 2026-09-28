"""The v1 React pages, served unchanged (Phase 6): /viz/offense, /viz/defense,
/viz/matchups and the /matchups/ alias.

app/static/viz is v1's built bundle, copied verbatim; the pages talk to the
ported JSON APIs (app/env.py, app/matchups.py) whose contracts are v1's. The
bundle picks its page from the URL and reads `window.__SEASON_CTX__` for the
season it opens on (v1 season_ctx.script_tag); both are injected here, derived
from the marts each page reads, so a new season needs no rebuild of the bundle.

Only ported pages are routed. v1's other /viz pages (scatter, player, draft...)
and the chat side panels call APIs v2 does not have yet, so they 404 rather
than render half-working.
"""
import json
from pathlib import Path

from flask import Blueprint, Response, request

from . import theme
from .matchups import _db, _default_week

bp = Blueprint("viz", __name__)
VIZ = Path(__file__).parent / "static" / "viz"


def _surface(conn, table):
    seasons = [r[0] for r in conn.execute(f"SELECT DISTINCT season FROM {table} WHERE season_type = 'REG' ORDER BY season DESC")]
    if not seasons:
        return None
    week = conn.execute(f"SELECT MAX(week) FROM {table} WHERE season = ? AND season_type = 'REG'", (seasons[0],)).fetchone()[0]
    return {"season": seasons[0], "week": week, "next_week": week, "seasons": seasons}


def season_ctx(conn) -> dict:
    out = {"offense": _surface(conn, "mart_team_off_env_week"), "defense": _surface(conn, "mart_team_def_env_week")}
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM mart_team_week_opponent ORDER BY season DESC")]
    if seasons:
        wk = _default_week(conn, seasons[0])
        out["matchups"] = {"season": seasons[0], "week": wk, "next_week": wk, "seasons": seasons}
    return {k: v for k, v in out.items() if v}


def _shell():
    html = (VIZ / "index.html").read_text(encoding="utf-8")
    style = theme.accent_style(request.path)
    conn = _db()
    try:
        ctx = f"<script>window.__SEASON_CTX__={json.dumps(season_ctx(conn), separators=(',', ':'))};</script>"
    finally:
        conn.close()
    html = html.replace("</head>", style + ctx + "</head>", 1)
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"   # the entry names hashed assets
    return resp


for _path in ("/viz/offense", "/viz/defense", "/viz/matchups", "/matchups/"):
    bp.add_url_rule(_path, f"viz_{_path.strip('/').replace('/', '_')}", _shell)
