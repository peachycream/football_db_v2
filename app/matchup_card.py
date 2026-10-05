"""/matchup/ : review the Matchup of the Week card BEFORE anything is posted. Reads mart_matchup_card* only
(through fdb/matchup_card.py, which the Discord job will share) and writes nothing. Nothing on this page sends
a message anywhere."""
import html
import sqlite3
from urllib.parse import urlencode

from flask import Blueprint, Response, jsonify, request

from fdb import card_render, config, matchup_card as mc, matchup_commentary, matchup_weeks

from .shell import page_shell

bp = Blueprint("matchup_card", __name__)
PATH = "/matchup/"


def _db():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _e(x):
    return html.escape("" if x is None else str(x))


def _int(name):
    try:
        return int(request.args.get(name, ""))
    except ValueError:
        return None


def _url(**kw):
    return PATH + "?" + urlencode({k: v for k, v in kw.items() if v not in (None, "")})


def _resolve(conn):
    lgs = mc.leagues(conn)
    league, season, week = mc.resolve(conn, request.args.get("league"), _int("season"), _int("week"))
    return league, season, week, lgs


PAGE_CSS = """
<style>
.mx-wrap{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start}
.mx-side{width:320px;max-width:100%}
.mx-main{flex:1 1 420px;min-width:0;max-width:100%;overflow-x:auto}
.mx-h{font-size:.7rem;letter-spacing:.08em;color:var(--tx-mut);margin:14px 0 6px;font-weight:700}
.mx-chips a{display:inline-block;padding:3px 9px;margin:0 4px 4px 0;border:1px solid var(--edge);border-radius:99px;color:var(--tx);text-decoration:none;font-size:.78rem}
.mx-chips a.on{border-color:var(--accent);color:var(--accent);font-weight:700}
.mx-game{display:block;padding:8px 10px;border:1px solid var(--edge);border-radius:8px;margin-bottom:6px;color:var(--tx);text-decoration:none;font-size:.8rem}
.mx-game.on{border-color:var(--accent);background:var(--surf-2)}
.mx-game .st{float:right;font-size:.65rem;letter-spacing:.06em;color:var(--tx-mut)}
.mx-game small{display:block;color:var(--tx-mut);margin-top:2px}
.mx-t{font-size:.78rem;margin-bottom:6px;color:var(--tx-mut)}.mx-t a{color:var(--accent)}
.mx-banner{border:1px solid var(--edge);border-left:3px solid var(--accent);padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:.82rem;color:var(--tx-mut)}
.mx-break{max-width:680px;margin-top:16px;font-size:.88rem;line-height:1.55}.mx-break p{margin:0 0 10px}
.mx-notes{margin-top:14px;font-size:.78rem;color:var(--tx-mut);max-width:680px}
.mx-notes li{margin:0 0 4px 18px}
</style>
"""


@bp.route(PATH)
def page():
    conn = _db()
    try:
        league, season, week, lgs = _resolve(conn)
        if league is None:
            return page_shell("Matchup card", '<div class="alert">No matchup data yet. Run <code>fdb weekly</code> '
                              "(or <code>fdb update mfl.weekly_results --apply</code> and the matchup builder).</div>", active=PATH)
        gs = mc.games(conn, league, season, week)
        home, away = request.args.get("home"), request.args.get("away")
        pick = next((g for g in gs if g["home_id"] == home and g["away_id"] == away), gs[0] if gs else None)
        p = mc.matchup_pick.pick(conn, league, season, week)
        basis = mc.matchup_pick.BASIS_TEXT.get(p["basis"], "")
        banner = ('<div class="mx-banner"><b>Review only.</b> This page never sends anything. It shows what the card would '
                  "contain for each game; the Discord post is a separate step that is not built yet. "
                  f"Games are ranked by the featured-game picker (a port of v1's selector), using {_e(basis)}. "
                  "The top game is the one that would be featured.</div>")
        lg_chips = "".join(f'<a class="{"on" if x["league_id"] == league else ""}" href="{_e(_url(league=x["league_id"]))}">{_e(x["name"])}</a>'
                           for x in lgs)
        s_chips = "".join(f'<a class="{"on" if s == season else ""}" href="{_e(_url(league=league, season=s))}">{s}</a>'
                          for s in mc.seasons(conn, league))
        ws = mc.weeks(conn, league, season)
        w_chips = "".join(f'<a class="{"on" if w["week"] == week else ""}" title="{_e(w["state"])}" '
                          f'href="{_e(_url(league=league, season=season, week=w["week"]))}">{w["week"]}'
                          f'{"" if w["state"] == "FINAL" else " *"}</a>' for w in ws)
        rows = ""
        for g in gs:
            on = pick is not None and g["home_id"] == pick["home_id"] and g["away_id"] == pick["away_id"]
            score = (f' &middot; {g["away_score"]:,.2f} to {g["home_score"]:,.2f}'
                     if g["state"] == "FINAL" and g["home_score"] is not None else "")
            rows += (f'<a class="mx-game {"on" if on else ""}" href="{_e(_url(league=league, season=season, week=week, home=g["home_id"], away=g["away_id"]))}">'
                     f'<span class="st">{"&#9733; FEATURED &middot; " if g["featured"] else ""}{_e(g["state"])}{" &middot; RIVALRY" if g["rivalry"] else ""}</span>'
                     f'<b>{_e(g["away_name"])}</b> at <b>{_e(g["home_name"])}</b>'
                     f'<small>{_e(g["away_record"])} / {_e(g["home_record"])} before the week{score}</small></a>')
        rt, pt = matchup_weeks.recap_target(conn, league, season), matchup_weeks.preview_target(conn, league, season)

        def target_line(label, t):
            if t["week"] is None:
                return f'<div class="mx-t"><b>{label}</b>: {_e(t["reason"])}</div>'
            link = _url(league=t["league"], season=t["season"], week=t["week"],
                        home=(t["featured"] or {}).get("home_id"), away=(t["featured"] or {}).get("away_id"))
            ok = "ready" if t["ready"] else "not ready"
            why = f' &mdash; {_e(t["reason"])}' if t["reason"] else ""
            return f'<div class="mx-t"><b>{label}</b>: <a href="{_e(link)}">week {t["week"]}</a> ({ok}){why}</div>'
        targets = ('<div class="mx-h">WHAT A JOB WOULD POST</div>' + target_line("Recap", rt) + target_line("Preview", pt))
        left = (f'<div class="mx-side">{targets}<div class="mx-h">LEAGUE</div><div class="mx-chips">{lg_chips}</div>'
                f'<div class="mx-h">SEASON</div><div class="mx-chips">{s_chips}</div>'
                f'<div class="mx-h">WEEK (* = not final)</div><div class="mx-chips">{w_chips}</div>'
                f'<div class="mx-h">{len(gs)} GAMES</div>{rows}</div>')
        if pick is None:
            main = '<div class="alert">No games for this week.</div>'
        else:
            c = mc.card(conn, league, season, week, pick["home_id"], pick["away_id"])
            notes = "".join(f"<li>{_e(n)}</li>" for n in c["notes"])
            if c["pick"]:
                notes += "".join(f"<li>{_e(n)}</li>" for n in c["pick"]["why"])
            facts = (f"State {c['state']}; lineups from {c['lineup_source'].replace('_', ' ')}; "
                     f"projection snapshot {c['proj_snapshot_at'] or 'none before kickoff'}.")
            q = urlencode({"league": league, "season": season, "week": week, "home": pick["home_id"], "away": pick["away_id"]})
            paras = matchup_commentary.paragraphs(conn, c)
            breakdown = ""
            if paras:
                body = "".join(f'<p><b>{_e(p["lead"])}.</b> {_e(p["text"])}</p>' for p in paras)
                breakdown = (f'<div class="mx-break"><div class="mx-h">THE BREAKDOWN (posted as the third message)</div>{body}</div>')
            links = (f'<a href="/api/matchup/card?{_e(q)}">card data (JSON)</a> &middot; '
                     f'<a href="/matchup/card/?{_e(q)}">card only</a> &middot; '
                     f'<a href="/matchup/panel.png?which=cover&amp;{_e(q)}">cover image</a> &middot; '
                     f'<a href="/matchup/panel.png?which=board&amp;{_e(q)}">board image</a> &middot; '
                     f'<a href="/matchup/card.png?{_e(q)}">whole card as one tall PNG</a>')
            main = (f'<div class="mx-main">{mc.card_html(c)}{breakdown}'
                    f'<div class="mx-notes"><div>{_e(facts)} {links}</div>'
                    f'{"<ul>" + notes + "</ul>" if notes else ""}</div></div>')
        return page_shell("Matchup card", PAGE_CSS + banner + f'<div class="mx-wrap">{left}{main}</div>', active=PATH)
    finally:
        conn.close()


@bp.route("/matchup/card/")
def card_only():
    """The card and nothing else, on a dark ground: what the image renderer will capture."""
    conn = _db()
    try:
        league, season, week, _ = _resolve(conn)
        c = mc.card(conn, league, season, week, request.args.get("home"), request.args.get("away")) if league else None
        if c is None:
            return "No such game.", 404
        return ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{_e(c["home"]["name"])} v {_e(c["away"]["name"])}</title></head>'
                f'<body style="margin:0;padding:16px;background:#05070d">{mc.card_html(c)}</body></html>')
    finally:
        conn.close()


@bp.route("/matchup/card.png")
def card_png():
    """The card as the PNG a Discord post would carry. Rendered on request (a few seconds: Chromium starts cold) and never
    cached, so it always matches the data. Posts nothing."""
    conn = _db()
    try:
        league, season, week, _ = _resolve(conn)
        c = mc.card(conn, league, season, week, request.args.get("home"), request.args.get("away")) if league else None
    finally:
        conn.close()
    if c is None:
        return "No such game.", 404
    try:
        png = card_render.render_png(c)
    except card_render.RenderError as e:
        return f"Could not render the card: {e}", 503
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@bp.route("/matchup/panel.png")
def panel_png():
    """One of the two landscape panels a Discord post carries (`which` = cover or board). Rendered on request, never cached."""
    which = request.args.get("which", "")
    if which not in mc.PANELS:
        return f"which must be one of: {', '.join(mc.PANELS)}", 400
    conn = _db()
    try:
        league, season, week, _ = _resolve(conn)
        c = mc.card(conn, league, season, week, request.args.get("home"), request.args.get("away")) if league else None
    finally:
        conn.close()
    if c is None:
        return "No such game.", 404
    try:
        png = card_render.render_panels(c)[which]
    except card_render.RenderError as e:
        return f"Could not render the panel: {e}", 503
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@bp.route("/api/matchup/games")
def api_games():
    conn = _db()
    try:
        league, season, week, _ = _resolve(conn)
        if league is None:
            return jsonify({"games": []})
        return jsonify({"league_id": league, "season": season, "week": week, "games": mc.games(conn, league, season, week)})
    finally:
        conn.close()


@bp.route("/api/matchup/card")
def api_card():
    conn = _db()
    try:
        league, season, week, _ = _resolve(conn)
        home, away = request.args.get("home"), request.args.get("away")
        c = mc.card(conn, league, season, week, home, away) if league else None
        if c is None:
            return jsonify({"error": "no such game"}), 404
        return jsonify(c)
    finally:
        conn.close()
