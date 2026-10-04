"""/matchup/ : review the Matchup of the Week card BEFORE anything is posted. Reads mart_matchup_card* only
(through fdb/matchup_card.py, which the Discord job will share) and writes nothing. Nothing on this page sends
a message anywhere."""
import html
import sqlite3
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request

from fdb import config, matchup_card as mc

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
    """(league, season, week) from the query, falling back to: league 30590 or the first with rows, its newest season,
    its newest week."""
    lgs = mc.leagues(conn)
    if not lgs:
        return None, None, None, lgs
    ids = [x["league_id"] for x in lgs]
    league = request.args.get("league") if request.args.get("league") in ids else ("30590" if "30590" in ids else ids[0])
    ss = mc.seasons(conn, league)
    season = _int("season") if _int("season") in ss else ss[0]
    ws = [w["week"] for w in mc.weeks(conn, league, season)]
    week = _int("week") if _int("week") in ws else ws[0]
    return league, season, week, lgs


PAGE_CSS = """
<style>
.mx-wrap{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start}
.mx-side{width:320px;max-width:100%}
.mx-main{flex:1;min-width:320px}
.mx-h{font-size:.7rem;letter-spacing:.08em;color:var(--tx-mut);margin:14px 0 6px;font-weight:700}
.mx-chips a{display:inline-block;padding:3px 9px;margin:0 4px 4px 0;border:1px solid var(--edge);border-radius:99px;color:var(--tx);text-decoration:none;font-size:.78rem}
.mx-chips a.on{border-color:var(--accent);color:var(--accent);font-weight:700}
.mx-game{display:block;padding:8px 10px;border:1px solid var(--edge);border-radius:8px;margin-bottom:6px;color:var(--tx);text-decoration:none;font-size:.8rem}
.mx-game.on{border-color:var(--accent);background:var(--surf-2)}
.mx-game .st{float:right;font-size:.65rem;letter-spacing:.06em;color:var(--tx-mut)}
.mx-game small{display:block;color:var(--tx-mut);margin-top:2px}
.mx-banner{border:1px solid var(--edge);border-left:3px solid var(--accent);padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:.82rem;color:var(--tx-mut)}
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
        banner = ('<div class="mx-banner"><b>Review only.</b> This page never sends anything. It shows what the card would '
                  "contain for each game; the Discord post is a separate step that is not built yet. The featured-game "
                  "picker is not ported yet, so games are listed strongest first (by the weaker team's record) and any can be opened.</div>")
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
                     f'<span class="st">{_e(g["state"])}{" &middot; RIVALRY" if g["rivalry"] else ""}</span>'
                     f'<b>{_e(g["away_name"])}</b> at <b>{_e(g["home_name"])}</b>'
                     f'<small>{_e(g["away_record"])} / {_e(g["home_record"])} before the week{score}</small></a>')
        left = (f'<div class="mx-side"><div class="mx-h">LEAGUE</div><div class="mx-chips">{lg_chips}</div>'
                f'<div class="mx-h">SEASON</div><div class="mx-chips">{s_chips}</div>'
                f'<div class="mx-h">WEEK (* = not final)</div><div class="mx-chips">{w_chips}</div>'
                f'<div class="mx-h">{len(gs)} GAMES</div>{rows}</div>')
        if pick is None:
            main = '<div class="alert">No games for this week.</div>'
        else:
            c = mc.card(conn, league, season, week, pick["home_id"], pick["away_id"])
            notes = "".join(f"<li>{_e(n)}</li>" for n in c["notes"])
            facts = (f"State {c['state']}; lineups from {c['lineup_source'].replace('_', ' ')}; "
                     f"projection snapshot {c['proj_snapshot_at'] or 'none before kickoff'}.")
            main = (f'<div class="mx-main">{mc.card_html(c)}'
                    f'<div class="mx-notes"><div>{_e(facts)} <a href="/api/matchup/card?'
                    f'{_e(urlencode({"league": league, "season": season, "week": week, "home": pick["home_id"], "away": pick["away_id"]}))}">card data (JSON)</a> &middot; <a href="/matchup/card/?'
                    f'{_e(urlencode({"league": league, "season": season, "week": week, "home": pick["home_id"], "away": pick["away_id"]}))}">card only</a></div>'
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
