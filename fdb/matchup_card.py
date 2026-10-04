"""The Matchup of the Week card: data and HTML, from mart_matchup_card* ONLY (apps and the Discord job read marts).

card()      -> a plain dict with every number the card shows, each already labelled projected or actual
card_html() -> one self-contained HTML fragment (inline CSS scoped to .mc) that renders that dict

Rates are computed here, at read time (win probability from the stored point totals), never stored.
Every string from the database is HTML-escaped; a logo URL is used only if it is http(s)."""
import html
import math
import re

from . import matchup_pick

GROUPS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")   # PK and OTHER are not on the position board (v1 parity)
FALLBACK = ("#5AA7E6", "#FB4F14")
BG = "#0D1220"
MIN_COLOR_DISTANCE = 90   # RGB distance below which two team colors read as the same on screen
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ------------------------------------------------------------------- queries --
def league_name(conn, league):
    r = conn.execute("SELECT name FROM my_franchises WHERE platform = 'mfl' AND league_id = ? ORDER BY season DESC LIMIT 1",
                     (league,)).fetchone()
    return r[0] if r else league


def leagues(conn):
    ids = [r[0] for r in conn.execute("SELECT DISTINCT league_id FROM mart_matchup_card ORDER BY league_id")]
    return [{"league_id": i, "name": league_name(conn, i)} for i in ids]


def resolve(conn, league=None, season=None, week=None):
    """(league, season, week) with anything missing or unknown replaced by a default: league 30590 (else the first with
    rows), its newest season, that season's newest week. (None, None, None) when there is no data."""
    ids = [x["league_id"] for x in leagues(conn)]
    if not ids:
        return None, None, None
    league = league if league in ids else ("30590" if "30590" in ids else ids[0])
    ss = seasons(conn, league)
    season = season if season in ss else ss[0]
    ws = [w["week"] for w in weeks(conn, league, season)]
    return league, season, (week if week in ws else ws[0])


def seasons(conn, league):
    return [r[0] for r in conn.execute("SELECT DISTINCT season FROM mart_matchup_card WHERE league_id = ? ORDER BY season DESC", (league,))]


def weeks(conn, league, season):
    """[{week, state}] newest first; state = the week's state (FINAL once the week is complete)."""
    out = []
    for r in conn.execute("""SELECT week, MIN(state) lo, MAX(state) hi FROM mart_matchup_card
                             WHERE league_id = ? AND season = ? GROUP BY week ORDER BY week DESC""", (league, season)):
        out.append({"week": r["week"], "state": _week_state(conn, league, season, r["week"])})
    return out


def _week_state(conn, league, season, week):
    s = {r[0] for r in conn.execute("SELECT DISTINCT state FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ?",
                                    (league, season, week))}
    return "FINAL" if s == {"FINAL"} else "LIVE" if "LIVE" in s else "PREVIEW" if "PREVIEW" in s else "FINAL"


def _winpct(w, l, t):
    g = w + l + t
    return (w + 0.5 * t) / g if g else 0.5


def games(conn, league, season, week):
    """The week's games, best first by the featured-game picker (fdb/matchup_pick.py: v1's selector); rank 1 is the
    featured game. Each row says which one it is and carries its pick score."""
    p = matchup_pick.pick(conn, league, season, week)
    rank = {(g["home_id"], g["away_id"]): g for g in p["ranked"]}
    rows = conn.execute("SELECT * FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ?",
                        (league, season, week)).fetchall()
    out = []
    for r in rows:
        k = rank.get((r["home_id"], r["away_id"]))
        out.append({"home_id": r["home_id"], "away_id": r["away_id"], "home_name": r["home_name"], "away_name": r["away_name"],
                    "home_abbrev": r["home_abbrev"], "away_abbrev": r["away_abbrev"], "state": r["state"],
                    "home_record": rec(r["home_w"], r["home_l"], r["home_t"]), "away_record": rec(r["away_w"], r["away_l"], r["away_t"]),
                    "home_score": r["home_score"], "away_score": r["away_score"], "rivalry": bool(r["is_division_rivalry"]),
                    "rank": k["rank"] if k else None, "featured": bool(k and k["rank"] == 1),
                    "pick_score": k["score"] if k else None, "pick_basis": p["basis"]})
    out.sort(key=lambda g: (g["rank"] is None, g["rank"] or 0, g["home_id"], g["away_id"]))
    return out


def rec(w, l, t):
    return f"{w}-{l}" + (f"-{t}" if t else "")


# --------------------------------------------------------------------- colors --
def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _distance(a, b):
    return math.dist(_rgb(a), _rgb(b))


def _ok(c):
    return bool(c) and bool(_HEX.match(c))


def pick_colors(home, home_alt, away, away_alt):
    """(home, away) accents. A missing/invalid color falls back; two colors too close on a dark card take the away
    team's alternate (then the home team's); if still close the fallback pair is used, so the two sides always differ."""
    h = home if _ok(home) else FALLBACK[0]
    a = away if _ok(away) else FALLBACK[1]
    if _distance(h, a) < MIN_COLOR_DISTANCE:
        for cand_a, cand_h in ((away_alt, h), (away, home_alt), (away_alt, home_alt)):
            cand_a = cand_a if _ok(cand_a) else a
            cand_h = cand_h if _ok(cand_h) else h
            if _distance(cand_h, cand_a) >= MIN_COLOR_DISTANCE:
                return cand_h, cand_a
        return FALLBACK
    return h, a


def tint(color, amount=0.24):
    """The team color mixed into the card background: a dark panel of that hue."""
    r, g, b = _rgb(color)
    br, bg_, bb = _rgb(BG)
    mix = lambda x, y: round(y + (x - y) * amount)
    return "#%02X%02X%02X" % (mix(r, br), mix(g, bg_), mix(b, bb))


def lighten(color, amount=0.35):
    r, g, b = _rgb(color)
    mix = lambda x: round(x + (255 - x) * amount)
    return "#%02X%02X%02X" % (mix(r), mix(g), mix(b))


# ----------------------------------------------------------------------- data --
def win_probability(home_proj, away_proj):
    """v1's model: a logistic of the projected margin over 5% of the combined projection. Not calibrated against
    results (open item); the card labels it as a projection edge."""
    if home_proj is None or away_proj is None:
        return None
    z = (home_proj - away_proj) / max((home_proj + away_proj) * 0.05, 1.0)
    p = 1 / (1 + math.exp(-z))
    return {"home": p, "away": 1 - p}


def card(conn, league, season, week, home, away):
    r = conn.execute("SELECT * FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ? AND home_id = ? AND away_id = ?",
                     (league, season, week, home, away)).fetchone()
    if r is None:
        return None
    final = r["state"] == "FINAL"
    side = lambda k: {"id": r[f"{k}_id"], "name": r[f"{k}_name"] or r[f"{k}_id"], "abbrev": r[f"{k}_abbrev"] or r[f"{k}_id"],
                      "division": r[f"{k}_division"], "logo": r[f"{k}_logo"], "w": r[f"{k}_w"], "l": r[f"{k}_l"], "t": r[f"{k}_t"],
                      "pf": r[f"{k}_pf"], "score": r[f"{k}_score"], "opt": r[f"{k}_opt_pts"], "proj": r[f"{k}_proj"],
                      "proj_missing": r[f"{k}_proj_missing"]}
    H, A = side("home"), side("away")
    hc, ac = pick_colors(r["home_color"], r["home_color_alt"], r["away_color"], r["away_color_alt"])
    H["color"], A["color"] = hc, ac
    notes = []
    # position board: actual points for a FINAL game, projections otherwise; never mixed, never guessed
    grp = {(x["franchise_id"], x["grp"]): dict(x) for x in conn.execute(
        "SELECT franchise_id, grp, n_starters, proj, actual FROM mart_matchup_card_groups WHERE league_id = ? AND season = ? AND week = ?",
        (league, season, week))}
    key = "actual" if final else "proj"
    board = []
    for g in GROUPS:
        hv = (grp.get((H["id"], g)) or {}).get(key)
        av = (grp.get((A["id"], g)) or {}).get(key)
        if hv is None and av is None:
            continue
        hv, av = hv or 0.0, av or 0.0
        board.append({"grp": g, "home": hv, "away": av, "edge": hv - av})
    board_basis = ("actual" if final else "projected") if board else None
    biggest = max(board, key=lambda b: abs(b["edge"]))["grp"] if board else None
    if not final and r["proj_snapshot_at"] is None:
        notes.append("No projection was captured before kickoff for this week, so projected points, the position board and "
                     "win probability are not shown. They start with the first week the loader fetched before kickoff.")
    if r["lineup_source"] == "upcoming_snapshot":
        notes.append(f"Lineups are the last MFL snapshot ({r['upcoming_snapshot_at']}); they can change until kickoff.")
    pl = conn.execute("""SELECT franchise_id, display_name, source_player_id, position, grp, proj, actual FROM mart_matchup_card_players
                         WHERE league_id = ? AND season = ? AND week = ? AND franchise_id IN (?, ?)""",
                      (league, season, week, H["id"], A["id"])).fetchall()
    unresolved = sum(1 for p in pl if p["display_name"] is None)
    if unresolved:
        notes.append(f"{unresolved} starters have no player identity yet (shown by MFL id).")
    sortkey = "actual" if final else "proj"
    players = {}
    for who, s in (("home", H), ("away", A)):
        ps = [p for p in pl if p["franchise_id"] == s["id"] and p[sortkey] is not None]
        ps.sort(key=lambda p: (-p[sortkey], p["source_player_id"]))
        players[who] = [{"name": p["display_name"] or f"MFL {p['source_player_id']}", "position": p["position"] or "?",
                         "value": p[sortkey]} for p in ps[:3]]
    players_basis = ("actual" if final else "projected") if (players["home"] or players["away"]) else None
    winner = margin = None
    if final and H["score"] is not None and A["score"] is not None:
        margin = abs(H["score"] - A["score"])
        winner = "home" if H["score"] > A["score"] else "away" if A["score"] > H["score"] else "tie"
    out = {"league_id": league, "league_name": league_name(conn, league), "season": season, "week": week, "state": r["state"],
           "home": H, "away": A, "rivalry": bool(r["is_division_rivalry"]), "winner": winner, "margin": margin,
           "win_prob": None if final else win_probability(H["proj"], A["proj"]),
           "board": board, "board_basis": board_basis, "biggest": biggest,
           "series": {"meetings": r["series_meetings"], "home_wins": r["series_home_wins"], "away_wins": r["series_away_wins"],
                      "ties": r["series_ties"], "last": None if r["last_meeting_season"] is None else {
                          "season": r["last_meeting_season"], "week": r["last_meeting_week"],
                          "home_score": r["last_meeting_home_score"], "away_score": r["last_meeting_away_score"]}},
           "players": players, "players_basis": players_basis, "proj_snapshot_at": r["proj_snapshot_at"],
           "lineup_source": r["lineup_source"], "notes": notes}
    out["takeaways"] = takeaways(out)
    p = matchup_pick.pick(conn, league, season, week)
    me = next((g for g in p["ranked"] if g["home_id"] == home and g["away_id"] == away), None)
    out["featured"] = bool(me and me["rank"] == 1)
    out["pick"] = None if me is None else {
        "rank": me["rank"], "of": len(p["ranked"]), "score": me["score"], "basis": p["basis"], "pedigree": p["pedigree"],
        "quality_home": me["quality_home"], "quality_away": me["quality_away"], "closeness": me["closeness"], "size": me["size"],
        "why": why(me, out, p)}
    return out


def why(me, c, p):
    """Plain-language reasons for the pick, from the same numbers the scorer used."""
    H, A = c["home"]["name"], c["away"]["name"]
    out = [f"Ranked {me['rank']} of {len(p['ranked'])} games using {matchup_pick.BASIS_TEXT[p['basis']]}.",
           f"Team quality (record blended with last season and roster strength): {H} {me['quality_home']:.2f}, {A} {me['quality_away']:.2f}."]
    if me["closeness"] is not None:
        out.append(f"Closeness of the two starter totals {me['closeness']:.2f}; size of the combined total {me['size']:.2f} "
                   f"(0 = smallest game of the week, 1 = biggest).")
    if not p["pedigree"]:
        out.append("No last-season results for this league, so quality uses this season's record and roster strength only.")
    return out


def takeaways(c):
    """Three short lines derived from the SAME numbers the graphics show, so text and numbers cannot disagree."""
    H, A, out = c["home"], c["away"], []
    b = c["board"]
    if b:
        top = max(b, key=lambda x: abs(x["edge"]))
        who = H if top["edge"] > 0 else A
        out.append(("flame", f"Biggest edge: {who['name']} at {top['grp']}, {abs(top['edge']):,.1f} "
                             f"{'points' if c['board_basis'] == 'actual' else 'projected points'}."))
        wins = {"home": [x for x in b if x["edge"] > 0], "away": [x for x in b if x["edge"] < 0]}
        lead = max(wins, key=lambda k: (len(wins[k]), sum(abs(x["edge"]) for x in wins[k])))
        s = H if lead == "home" else A
        best = sorted(wins[lead], key=lambda x: -abs(x["edge"]))[:3]
        if best:
            out.append(("bolt", f"{s['name']} leads {len(wins[lead])} of {len(b)} position groups: "
                                + ", ".join(f"{x['grp']} +{abs(x['edge']):,.1f}" for x in best) + "."))
    if c["state"] == "FINAL" and c["margin"] is not None:
        win = H if c["winner"] == "home" else A if c["winner"] == "away" else None
        left = sum((s["opt"] - s["score"]) for s in (H, A) if s["opt"] is not None and s["score"] is not None)
        out.append(("scale", (f"{win['name']} won by {c['margin']:,.2f}. " if win else "Tied. ")
                    + f"Between them {left:,.1f} points stayed on the bench."))
    elif H["proj"] is not None and A["proj"] is not None:
        gap, tot = abs(H["proj"] - A["proj"]), H["proj"] + A["proj"]
        out.append(("scale", f"Projected gap is {gap:,.1f} points on about {tot / 2:,.0f} each"
                             + (". Close enough that lineup calls decide it." if gap < 0.08 * tot / 2 else ".")))
    return out[:3]


# ------------------------------------------------------------------------ html --
CSS = """
.mc{max-width:680px;background:#0d1220;border-radius:14px;overflow:hidden;color:#eef1f7;border:1px solid #232b40;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.35}
.mc *{box-sizing:border-box}
.mc .top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid #232b40;font-size:12px;color:#8e98b3}
.mc .pill{font-size:11px;font-weight:500;padding:3px 9px;border-radius:99px;margin-left:6px;display:inline-block}
.mc .hero{position:relative;display:grid;grid-template-columns:1fr 1fr;min-height:270px;overflow:hidden}
.mc .wm{position:absolute;top:50%;width:330px;height:330px;margin-top:-165px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:110px;font-weight:500;letter-spacing:-4px;overflow:hidden}
.mc .wm img{width:100%;height:100%;object-fit:contain}
.mc .side{position:relative;z-index:2;padding:34px 18px 22px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:4px}
.mc .nm{font-size:20px;font-weight:500;text-shadow:0 1px 3px #000a}
.mc .big{font-size:52px;font-weight:500;line-height:1.05;margin-top:6px;text-shadow:0 2px 6px #000b}
.mc .sub{font-size:12px;text-shadow:0 1px 3px #000a}
.mc .vs{position:absolute;z-index:3;left:50%;top:50%;transform:translate(-50%,-50%);width:52px;height:52px;border-radius:50%;background:#0d1220;border:2px solid #2d3652;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:500;color:#8e98b3}
.mc .tag{font-size:11px;font-weight:500;padding:3px 10px;border-radius:99px}
.mc .wp{padding:14px 16px 4px}
.mc .bar{display:flex;height:12px;border-radius:99px;overflow:hidden}
.mc .sec{padding:16px 16px 0}
.mc .lbl{font-size:12px;color:#8e98b3;margin-bottom:10px;display:flex;justify-content:space-between;gap:8px}
.mc .row{display:grid;grid-template-columns:34px 1fr 1fr 58px;align-items:center;height:28px;font-size:12px}
.mc .half{height:14px;background:#161d30;position:relative}
.mc .fill{position:absolute;top:0;bottom:0}
.mc .tape{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.mc .tape3{grid-template-columns:repeat(3,minmax(0,1fr))}
.mc .chip{background:#141b2e;border-radius:10px;padding:10px;font-size:12px;color:#8e98b3}
.mc .chip b{display:block;font-weight:500;font-size:15px;color:#eef1f7;margin-top:4px}
.mc .pl{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.mc .pr{display:flex;align-items:center;gap:9px;background:#141b2e;border-radius:10px;padding:8px 10px;margin-bottom:6px;font-size:13px}
.mc .av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:500;flex:none}
.mc .take{display:grid;gap:8px;padding:16px}
.mc .tk{display:flex;gap:10px;align-items:flex-start;font-size:13px;color:#c9d0e2}
.mc .tk b{flex:none;width:18px;text-align:center;font-weight:500}
.mc .muted{font-size:12px;color:#8e98b3;margin-top:8px}
@media (max-width:560px){.mc .tape{grid-template-columns:repeat(2,minmax(0,1fr))}.mc .big{font-size:40px}.mc .wm{width:240px;height:240px;margin-top:-120px}}
"""


def _e(x):
    return html.escape("" if x is None else str(x))


def _initials(name):
    parts = [p for p in re.split(r"[\s.]+", name or "") if p]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper() if parts else "?"


_DATA_LOGO = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$")


def _logo(url):
    """A logo is used only if it is an http(s) URL or an embedded PNG/JPEG/GIF/WEBP data URI (the PNG renderer's form)."""
    return url if url and (re.match(r"^https?://", url) or _DATA_LOGO.match(url)) else None


def card_html(c) -> str:
    AW, HM = c["away"], c["home"]   # left panel = away, right panel = home ("away at home")
    final, state = c["state"] == "FINAL", c["state"]
    lt, rt = tint(AW["color"], 0.30), tint(HM["color"], 0.30)
    lt_txt, rt_txt = lighten(AW["color"]), lighten(HM["color"])
    pills = ""
    if c.get("featured"):
        pills += '<span class="pill" style="background:#3a2f12;color:#ffd36b">Matchup of the week</span>'
    if c["rivalry"]:
        pills += '<span class="pill" style="background:#3a1d24;color:#ff9aa8">Division rivalry</span>'
    pill = {"FINAL": ("#12301f", "#7be0a4", "Final"), "LIVE": ("#33280f", "#ffd36b", "In progress"),
            "PREVIEW": ("#14283a", "#8fd0ff", "Preview")}[state]
    pills += f'<span class="pill" style="background:{pill[0]};color:{pill[1]}">{pill[2]}</span>'

    def wm(s, left):
        pos = "left:-70px" if left else "right:-70px"
        op = ".22" if not final or c["winner"] in (None, "tie") or (c["winner"] == ("away" if left else "home")) else ".10"
        logo = _logo(s["logo"])
        inner = (f'<img src="{_e(logo)}" alt="" onerror="this.style.display=\'none\'">' if logo
                 else f'<span>{_e(s["abbrev"])}</span>')
        ring = "" if logo else f"border:22px solid {s['color']};"
        return f'<div class="wm" style="{pos};color:{s["color"]};{ring}opacity:{op}">{inner}</div>'

    def side(s, who, txt):
        tag = ""
        if final and c["winner"] == who:
            tag = f'<span class="tag" style="background:{s["color"]};color:#0d1220">Winner</span>'
        if final:
            big = f'{s["score"]:,.2f}' if s["score"] is not None else "-"
            if c["margin"] is None or c["winner"] == "tie":
                sub = "Tied" if c["winner"] == "tie" else ""
            else:
                sub = f'Won by {c["margin"]:,.2f}' if c["winner"] == who else f'Lost by {c["margin"]:,.2f}'
            sub2, cap = f'{rec(s["w"], s["l"], s["t"])} before this week', "Final"
        else:
            big = f'{s["proj"]:,.1f}' if s["proj"] is not None else "-"
            sub = f'{rec(s["w"], s["l"], s["t"])} · {s["w"] + s["l"] + s["t"]} games played'
            sub2, cap = "", ("Projected" if s["proj"] is not None else "No pre-kickoff projection")
        line = lambda t: f'<div class="sub" style="color:{txt}">{_e(t)}</div>' if t else ""
        return (f'<div class="side">{tag}<div class="nm" style="color:{txt}">{_e(s["name"])}</div>{line(sub)}{line(sub2)}'
                f'<div class="big" style="color:{txt}">{_e(big)}</div>{line(cap)}</div>')

    hero = (f'<div class="hero"><div style="position:absolute;inset:0;background:{lt};clip-path:polygon(0 0,57% 0,43% 100%,0 100%)"></div>'
            f'<div style="position:absolute;inset:0;background:{rt};clip-path:polygon(57% 0,100% 0,100% 100%,43% 100%)"></div>'
            f'{wm(AW, True)}{wm(HM, False)}{side(AW, "away", lt_txt)}{side(HM, "home", rt_txt)}'
            f'<div class="vs">{"FINAL" if final else "VS"}</div></div>')

    wp = ""
    if c["win_prob"]:
        ph = c["win_prob"]["away"] * 100
        wp = (f'<div class="wp"><div class="bar"><div style="width:{ph:.1f}%;background:{AW["color"]}"></div>'
              f'<div style="width:2px;background:{BG}"></div><div style="flex:1;background:{HM["color"]}"></div></div>'
              f'<div style="display:flex;justify-content:space-between;font-size:12px;margin-top:6px">'
              f'<span style="color:{AW["color"]}">{c["win_prob"]["away"] * 100:.0f}%</span>'
              f'<span style="color:#8e98b3">Projection edge (v1 model)</span>'
              f'<span style="color:{HM["color"]}">{c["win_prob"]["home"] * 100:.0f}%</span></div></div>')

    board = ""
    if c["board"]:
        mx = max(abs(b["edge"]) for b in c["board"]) or 1.0
        rows = ""
        for b in c["board"]:
            w = round(abs(b["edge"]) / mx * 100)
            left = b["edge"] < 0   # negative edge = away leads = left
            col = AW["color"] if left else HM["color"]
            flame = "&#9733; " if b["grp"] == c["biggest"] else ""
            lh = (f'<div class="fill" style="right:0;width:{w}%;background:{col};border-radius:7px 0 0 7px"></div>' if left and w else "")
            rh = (f'<div class="fill" style="left:0;width:{w}%;background:{col};border-radius:0 7px 7px 0"></div>' if (not left) and w else "")
            rows += (f'<div class="row"><span style="font-weight:500">{b["grp"]}</span>'
                     f'<div class="half" style="border-radius:7px 0 0 7px">{lh}</div>'
                     f'<div class="half" style="border-radius:0 7px 7px 0;border-left:1px solid {BG}">{rh}</div>'
                     f'<span style="text-align:right;color:{col}">{flame}{abs(b["edge"]):,.1f}</span></div>')
        basis = "actual points" if c["board_basis"] == "actual" else "projected points"
        board = (f'<div class="sec"><div class="lbl"><span>Position edge &middot; {basis}</span>'
                 f'<span>&#9733; biggest swing</span></div>{rows}</div>')

    s = c["series"]
    if s["meetings"]:
        if s["home_wins"] == s["away_wins"]:
            line = f'Series tied {s["home_wins"]}-{s["away_wins"]}'
        elif s["home_wins"] > s["away_wins"]:
            line = f'{HM["abbrev"]} leads {s["home_wins"]}-{s["away_wins"]}'
        else:
            line = f'{AW["abbrev"]} leads {s["away_wins"]}-{s["home_wins"]}'
        line += (f' ({s["ties"]} tied)' if s["ties"] else "") + f' · {s["meetings"]} meetings'
        last = s["last"]
        lastline = (f'Last meeting: {last["season"]} week {last["week"]}, {HM["abbrev"]} {last["home_score"]:,.2f} '
                    f'to {AW["abbrev"]} {last["away_score"]:,.2f}') if last else ""
    else:
        line, lastline = "First regular-season meeting", ""
    line, lastline = _e(line), _e(lastline)
    tape = (f'<div class="sec"><div class="lbl"><span>Tale of the tape</span><span>before this week</span></div><div class="tape">'
            f'<div class="chip">{_e(AW["name"])} record<b style="color:{AW["color"]}">{_e(rec(AW["w"], AW["l"], AW["t"]))}</b></div>'
            f'<div class="chip">{_e(HM["name"])} record<b style="color:{HM["color"]}">{_e(rec(HM["w"], HM["l"], HM["t"]))}</b></div>'
            f'<div class="chip">Points for, season total<b style="font-size:13px"><span style="color:{AW["color"]}">{AW["pf"]:,.0f}</span> vs '
            f'<span style="color:{HM["color"]}">{HM["pf"]:,.0f}</span></b></div>'
            f'<div class="chip">All-time series<b style="font-size:13px">{line}</b></div></div>'
            + (f'<div class="muted">{lastline}</div>' if lastline else "") + '</div>')

    bench = ""
    if final and AW["opt"] is not None and HM["opt"] is not None and AW["score"] is not None and HM["score"] is not None:
        sh = lambda s_: (s_["score"] / s_["opt"] * 100) if s_["opt"] else 0.0
        bench = (f'<div class="sec"><div class="lbl"><span>Left on the bench</span></div><div class="tape tape3">'
                 f'<div class="chip">Best possible lineup<b style="font-size:14px"><span style="color:{AW["color"]}">{AW["opt"]:,.1f}</span> vs '
                 f'<span style="color:{HM["color"]}">{HM["opt"]:,.1f}</span></b></div>'
                 f'<div class="chip">Bench points left<b style="font-size:14px"><span style="color:{AW["color"]}">{AW["opt"] - AW["score"]:,.1f}</span> vs '
                 f'<span style="color:{HM["color"]}">{HM["opt"] - HM["score"]:,.1f}</span></b></div>'
                 f'<div class="chip">Share of best lineup<b style="font-size:14px"><span style="color:{AW["color"]}">{sh(AW):.1f}%</span> vs '
                 f'<span style="color:{HM["color"]}">{sh(HM):.1f}%</span></b></div></div></div>')

    players = ""
    if c["players_basis"]:
        def col(who, s_):
            rows = "".join(
                f'<div class="pr"><span class="av" style="background:{s_["color"]};color:#0d1220">{_e(_initials(p["name"]))}</span>'
                f'<span style="flex:1">{_e(p["name"])} <span style="color:#8e98b3">{_e(p["position"])}</span></span>'
                f'<span>{p["value"]:,.1f}</span></div>' for p in c["players"][who])
            return f'<div>{rows}</div>'
        title = "Top performers" if c["players_basis"] == "actual" else "Players to watch"
        sub = "Actual points" if c["players_basis"] == "actual" else "Projected points"
        players = (f'<div class="sec"><div class="lbl"><span>{title}</span><span>{sub}, week {c["week"]}</span></div>'
                   f'<div class="pl">{col("away", AW)}{col("home", HM)}</div></div>')

    icons = {"flame": "&#9733;", "bolt": "&#9889;", "scale": "&#9878;"}
    take = "".join(f'<div class="tk"><b>{icons.get(i, "&bull;")}</b><span>{_e(t)}</span></div>' for i, t in c["takeaways"])
    take = f'<div class="take">{take}</div>' if take else '<div style="height:16px"></div>'

    top = (f'<div class="top"><span>{_e(c["league_name"])} &middot; Week {c["week"]}{" recap" if final else ""}</span>'
           f'<span>{pills}</span></div>')
    return f'<style>{CSS}</style><div class="mc">{top}{hero}{wp}{board}{tape}{bench}{players}{take}</div>'
