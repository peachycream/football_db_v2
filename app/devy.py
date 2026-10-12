"""/devy/ : the CFB / devy tracker (Phase 14). Reads mart_devy_* only and writes nothing.

Roster = Turon's screenshots (app_devy_roster), linked to CFBD ids by his approved review sheet; MFL's devy slots
are placeholders and never read. Stats are CFBD (and PFF where he approved a link). Age is blank: no source has a
birthdate. Free agents are FBS players on no roster cell of the chosen league, ranked by `production_score`, a
ranking aid (formula in schema/043_mart_devy.sql), not a projection.
"""
import html
import sqlite3
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request

from fdb import config

from .shell import page_shell

bp = Blueprint("devy", __name__)
PATH = "/devy/"
GROUPS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")
SEASONS = (2026, 2025)
CLASS = {1: "FR", 2: "SO", 3: "JR", 4: "SR", 5: "GR"}


def _n(v, d=0):
    return "&ndash;" if v is None else f"{v:,.{d}f}"


def _yr(v):
    return "&ndash;" if v is None else str(int(v))


def _ht(inches):
    return "&ndash;" if not inches else f"{int(inches) // 12}'{int(inches) % 12}\""


# group -> [(header, key or callable, decimals)]. Names come from mart_devy_board / mart_devy_free_agents.
COLS = {
    "QB": [("Cmp/Att", lambda r: f"{_n(r['pass_cmp'])}/{_n(r['pass_att'])}", None), ("Yds", "pass_yds", 0), ("TD", "pass_td", 0),
           ("INT", "pass_int", 0), ("Cmp%", "pass_cmp_pct", 1), ("YPA", "pass_ypa", 1), ("Rush", "rush_yds", 0),
           ("Rush TD", "rush_td", 0), ("PFF pass", "pass_grade", 1), ("BTT%", "big_time_throw_rate", 1),
           ("TWP%", "turnover_worthy_rate", 1)],
    "RB": [("Car", "rush_att", 0), ("Yds", "rush_yds", 0), ("YPC", "rush_ypc", 1), ("TD", "rush_td", 0), ("Rec", "rec", 0),
           ("Rec yds", "rec_yds", 0), ("Rec TD", "rec_td", 0), ("PFF run", "run_grade", 1), ("Elusive", "elusive_rating", 1),
           ("Usage", "usage_overall", 3)],
    "WR": [("Rec", "rec", 0), ("Yds", "rec_yds", 0), ("YPR", "rec_ypr", 1), ("TD", "rec_td", 0), ("Rush yds", "rush_yds", 0),
           ("YPRR", "yprr", 2), ("Drop%", "drop_rate", 1), ("PFF route", "route_grade", 1), ("Usage", "usage_overall", 3)],
    "DL": [("Tkl", "tackles", 0), ("TFL", "tackles_for_loss", 1), ("Sacks", "sacks", 1), ("Hurries", "qb_hurries", 0),
           ("Pressures", "total_pressures", 0), ("PFF rush", "pass_rush_grade", 1), ("PFF def", "defense_grade", 1)],
    "LB": [("Tkl", "tackles", 0), ("TFL", "tackles_for_loss", 1), ("Sacks", "sacks", 1), ("PD", "pass_breakups", 0),
           ("INT", "def_int", 0), ("PFF cov", "coverage_grade", 1), ("PFF run D", "run_defense_grade", 1),
           ("PFF def", "defense_grade", 1)],
    "DB": [("Tkl", "tackles", 0), ("PD", "pass_breakups", 0), ("INT", "def_int", 0), ("TFL", "tackles_for_loss", 1),
           ("PFF cov", "coverage_grade", 1), ("PFF def", "defense_grade", 1)],
}
COLS["TE"] = COLS["WR"]


def _db():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _e(x):
    return html.escape("" if x is None else str(x))


def _url(**kw):
    return PATH + "?" + urlencode({k: v for k, v in kw.items() if v not in (None, "")})


def leagues(conn):
    return [dict(r) for r in conn.execute(
        "SELECT DISTINCT d.league_id, COALESCE(m.name, d.league_id) AS name FROM app_devy_roster d "
        "LEFT JOIN my_franchises m ON m.platform = 'mfl' AND m.league_id = d.league_id AND m.season = 2026 ORDER BY d.league_id")]


def board(conn, league, season):
    """One entry per player in the league: owners (mine first), stats row. A player on two franchises (league 55757
    holds two copies of each) appears once with both owners; a cell with no CFBD record is listed separately."""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM mart_devy_board WHERE league_id = ? AND (season = ? OR cfbd_id IS NULL) "
        "ORDER BY is_mine DESC, franchise_id, line, devy_slot", (league, season))]
    players, nostats = {}, []
    for r in rows:
        if r["cfbd_id"] is None:
            nostats.append(r)
            continue
        p = players.setdefault(r["cfbd_id"], {**r, "owners": [], "mine": False})
        p["owners"].append((r["franchise_name"] or r["franchise_id"], bool(r["is_mine"])))
        p["mine"] = p["mine"] or bool(r["is_mine"])
    # a mapped player CFBD has no row for in this season (e.g. a 2026 freshman viewed in 2025) is listed, not dropped
    for r in rows:
        if r["cfbd_id"] is not None and r["season"] is None and r["cfbd_id"] in players:
            players[r["cfbd_id"]]["_nostats"] = True
    return players, nostats


def _cells(group, r):
    out = []
    for _, key, d in COLS[group]:
        out.append(key(r) if callable(key) else _n(r.get(key), d))
    return out


def _table(group, plist, show_owner):
    head = ["Player", "School", "Cl", "Ht", "Wt", "Age", "Draft yr", "PFF elig.", "GP"] + [c[0] for c in COLS[group]] + ["Score"]
    if show_owner:
        head.insert(1, "Owner")
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = ""
    for r in plist:
        owner = ""
        if show_owner:
            own = "; ".join(f'<b class="dv-me">{_e(n)}</b>' if mine else _e(n) for n, mine in r["owners"])
            owner = f"<td>{own}</td>"
        cls = "dv-mine" if r.get("mine") else ""
        est = r.get("draft_class_est")
        if r.get("draft_season"):
            draft_cell = f"<td>{_yr(r['draft_season'])}</td>"
        elif est:
            draft_cell = ('<td title="Earliest draft class from CFBD class year: season + max(1, 4 - class). '
                          f'Ignores redshirts and early declarations.">{_yr(est)}<small> est.</small></td>')
        else:
            draft_cell = "<td>&ndash;</td>"
        elig = f"<td>{_yr(r.get('draft_eligible_season'))}</td>"
        cells = [f"<td class='dv-name'>{_e(r['name'])}<small>{_e(r['cfbd_position'])}</small></td>", owner,
                 f"<td>{_e(r['school'])}</td>", f"<td>{CLASS.get(r['class_year'], '&ndash;')}</td>", f"<td>{_ht(r['height_in'])}</td>",
                 f"<td>{_n(r['weight_lb'])}</td>", "<td>&ndash;</td>", draft_cell, elig, f"<td>{_n(r['games'])}</td>"]
        cells += [f"<td>{c}</td>" for c in _cells(group, r)]
        cells.append(f"<td><b>{_n(r['production_score'], 1)}</b></td>")
        body += f'<tr class="{cls}">{"".join(cells)}</tr>'
    return f'<div class="dv-scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


CSS = """
<style>
.dv-chips a{display:inline-block;padding:3px 10px;margin:0 4px 4px 0;border:1px solid var(--edge);border-radius:99px;color:var(--tx);text-decoration:none;font-size:.8rem}
.dv-chips a.on{border-color:var(--accent);color:var(--accent);font-weight:700}
.dv-h{font-size:.7rem;letter-spacing:.08em;color:var(--tx-mut);margin:16px 0 6px;font-weight:700}
.dv-note{border:1px solid var(--edge);border-left:3px solid var(--accent);padding:10px 14px;border-radius:6px;margin:12px 0;font-size:.82rem;color:var(--tx-mut)}
.dv-scroll{overflow-x:auto;max-width:100%;margin-bottom:6px}
.dv-scroll table{font-size:.8rem;white-space:nowrap}
tr.dv-mine td{background:rgb(var(--accent-rgb) / .10)}
tr.dv-mine td.dv-name{box-shadow:inset 3px 0 0 var(--accent)}
.dv-name small{color:var(--tx-mut);margin-left:6px;font-size:.68rem}
.dv-me{color:var(--accent)}
.dv-skip{font-size:.8rem;color:var(--tx-mut);margin-top:8px}
</style>
"""


@bp.route(PATH)
def page():
    conn = _db()
    try:
        lgs = leagues(conn)
        if not lgs:
            return page_shell("Devy tracker", '<div class="alert">No devy roster loaded yet.</div>', active=PATH)
        league = request.args.get("league") or lgs[0]["league_id"]
        if league not in {x["league_id"] for x in lgs}:
            league = lgs[0]["league_id"]
        try:
            season = int(request.args.get("season", SEASONS[0]))
        except ValueError:
            season = SEASONS[0]
        season = season if season in SEASONS else SEASONS[0]
        view = request.args.get("view", "board")
        pos = request.args.get("pos", "")
        pos = pos if pos in GROUPS else ""
        lg_chips = "".join(f'<a class="{"on" if x["league_id"] == league else ""}" href="{_e(_url(league=x["league_id"], season=season, view=view, pos=pos))}">{_e(x["name"])} &middot; {x["league_id"]}</a>' for x in lgs)
        s_chips = "".join(f'<a class="{"on" if s == season else ""}" href="{_e(_url(league=league, season=s, view=view, pos=pos))}">{s}</a>' for s in SEASONS)
        v_chips = "".join(f'<a class="{"on" if v == view else ""}" href="{_e(_url(league=league, season=season, view=v, pos=pos))}">{lab}</a>'
                          for v, lab in (("board", "Rostered players"), ("fa", "Free agents to watch")))
        p_chips = f'<a class="{"" if pos else "on"}" href="{_e(_url(league=league, season=season, view=view))}">All</a>' + "".join(
            f'<a class="{"on" if g == pos else ""}" href="{_e(_url(league=league, season=season, view=view, pos=g))}">{g}</a>' for g in GROUPS)
        top = (f'<div class="dv-note">Rosters are from your screenshots (dated per league); MFL devy slots are placeholders and are not used. '
               "Stats: CFBD, plus PFF grades where a link is approved. <b>Age is blank</b>: no source has a birthdate. "
               "<b>Draft yr</b> is the actual draft class once PFF shows the player declared, otherwise an <b>est.</b> of the earliest class from class year (3 years after high school; ignores redshirts and early declarations). <b>PFF elig.</b> is PFF's own eligibility year, which runs later than the earliest draft class (it looks like the end of college eligibility). <b>Score</b> is a ranking aid, not a projection "
               "(QB: 0.04/pass yd, 4/TD, -2/INT, 0.1/rush yd, 6/rush TD; RB/WR/TE: 0.1/yd, 6/TD, 0.5/rec; defense: 1/tackle, 1.5/TFL, "
               "4/sack, 4/INT, 1.5/PD, 1/hurry; season totals).</div>"
               f'<div class="dv-h">LEAGUE</div><div class="dv-chips">{lg_chips}</div>'
               f'<div class="dv-h">SEASON</div><div class="dv-chips">{s_chips}</div>'
               f'<div class="dv-h">VIEW</div><div class="dv-chips">{v_chips}</div>'
               f'<div class="dv-h">POSITION</div><div class="dv-chips">{p_chips}</div>')
        main = ""
        if view == "fa":
            for g in ([pos] if pos else GROUPS):
                rows = [dict(r, owners=[], mine=False) for r in conn.execute(
                    "SELECT * FROM mart_devy_free_agents WHERE league_id = ? AND season = ? AND position_group = ? "
                    "ORDER BY production_score DESC LIMIT 25", (league, season, g))]
                if rows:
                    main += f'<div class="dv-h">{g}: TOP {len(rows)} UNROSTERED IN THIS LEAGUE, BY SCORE</div>' + _table(g, rows, False)
        else:
            players, nostats = board(conn, league, season)
            mine = [p for p in players.values() if p["mine"]]
            for title, sel in (("YOUR PLAYERS", mine), ("OWNED BY OTHERS", [p for p in players.values() if not p["mine"]])):
                for g in ([pos] if pos else GROUPS):
                    plist = sorted((p for p in sel if p["position_group"] == g), key=lambda p: -(p["production_score"] or 0))
                    if plist:
                        main += f'<div class="dv-h">{title} &middot; {g} ({len(plist)})</div>' + _table(g, plist, True)
            if nostats and not pos:
                items = "; ".join(f"{_e(r['source_text'])} ({_e(r['franchise_name'])}): {_e(r['mapping_reason'])}" for r in nostats)
                main += f'<div class="dv-skip"><b>No CFBD record:</b> {items}</div>'
            seen = sorted({r["seen_on"] for r in conn.execute("SELECT seen_on FROM app_devy_roster WHERE league_id = ?", (league,))})
            main += f'<div class="dv-skip">Roster screenshot dated {_e(", ".join(seen))}. {len(players)} players on {len({o[0] for p in players.values() for o in p["owners"]})} franchises in view.</div>'
        return page_shell("Devy tracker", CSS + top + (main or '<div class="alert">Nothing to show for this selection.</div>'), active=PATH)
    finally:
        conn.close()


@bp.route("/api/devy/board")
def api_board():
    conn = _db()
    try:
        league = request.args.get("league", "")
        try:
            season = int(request.args.get("season", SEASONS[0]))
        except ValueError:
            season = SEASONS[0]
        players, nostats = board(conn, league, season)
        return jsonify({"league": league, "season": season, "players": list(players.values()), "no_cfbd_record": nostats})
    finally:
        conn.close()
