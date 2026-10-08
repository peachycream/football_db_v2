"""The written breakdown for a Matchup of the Week post: a handful of short paragraphs, each led by a bold label, generated
DETERMINISTICALLY from the numbers the card already shows (plus the week's league-wide context from mart_matchup_card).
No model writes it, so the words cannot disagree with the graphics and a re-run says the same thing.

recap_paragraphs(conn, card)    for a FINAL game: result, how it was won, the stars, the bench, the series, what is next
preview_paragraphs(conn, card)  for a PREVIEW/LIVE game: the matchup, position battles, players to watch, the series
to_markdown(paragraphs)         Discord markdown, trimmed to fit a message (the least important paragraphs go first)

Every paragraph is {"lead": "The result", "text": "..."} and is only emitted when its numbers exist: nothing is invented to
fill space. Reads the mart only; writes nothing."""


def ordinal(n: int) -> str:
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def week_context(conn, league, season, week) -> dict:
    """League-wide context for one completed week: every team's score (a franchise counted once), the score ranks and the
    margin ranks among the week's games."""
    rows = conn.execute("""SELECT home_id, away_id, home_score, away_score FROM mart_matchup_card
                           WHERE league_id = ? AND season = ? AND week = ? AND state = 'FINAL'
                             AND home_score IS NOT NULL AND away_score IS NOT NULL""", (league, season, week)).fetchall()
    team = {}
    margins = []
    for r in rows:
        team[r["home_id"]], team[r["away_id"]] = r["home_score"], r["away_score"]
        margins.append(abs(r["home_score"] - r["away_score"]))
    order = sorted(team.values(), reverse=True)
    return {"teams": len(team), "games": len(rows), "scores": team, "order": order, "margins": sorted(margins, reverse=True)}


def poss(name: str) -> str:
    """Possessive of a team name: Bengals -> Bengals', Giants -> Giants', Chiefs -> Chiefs' (all end in s)."""
    return name + ("'" if name.endswith("s") else "'s")


def _rank(value, descending_list):
    """1 + how many values are strictly higher (ties share a rank)."""
    return 1 + sum(1 for v in descending_list if v > value + 1e-9)


def _names(card):
    return card["home"], card["away"]


def _series_after(card):
    """(winner_wins, loser_wins, ties, meetings, phrase) AFTER this game, or None when playoffs/no result."""
    s, H, A = card["series"], card["home"], card["away"]
    if card["state"] != "FINAL" or card["winner"] not in ("home", "away") or card.get("is_playoff"):
        return None
    hw, aw, t, n = s["home_wins"], s["away_wins"], s["ties"], s["meetings"]
    win, lose = (H, A) if card["winner"] == "home" else (A, H)
    hw2, aw2 = hw + (card["winner"] == "home"), aw + (card["winner"] == "away")
    ww, lw = (hw2, aw2) if card["winner"] == "home" else (aw2, hw2)
    before_w, before_l = (hw, aw) if card["winner"] == "home" else (aw, hw)
    meetings = n + 1
    if n == 0:
        phrase = f"This was the first regular-season meeting between {win['name']} and {lose['name']}, and {win['name']} won it."
    elif ww > lw and before_w > before_l:
        phrase = f"{win['name']} extend their lead in the all-time series to {ww}-{lw}"
    elif ww > lw:
        phrase = f"{win['name']} take the lead in the all-time series, {ww}-{lw}"
    elif ww == lw:
        phrase = f"{win['name']} level the all-time series at {ww}-{lw}"
    else:
        phrase = f"{win['name']} cut their deficit in the all-time series to {ww}-{lw}"
    if n:
        phrase += f" across {meetings} regular-season meetings" + (f" ({t} tied)" if t else "") + "."
    return ww, lw, t, meetings, phrase


def _pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "0.0%"


def recap_paragraphs(conn, card) -> list:
    if card["state"] != "FINAL" or card["home"]["score"] is None or card["away"]["score"] is None:
        return []
    H, A = card["home"], card["away"]
    ctx = week_context(conn, card["league_id"], card["season"], card["week"])
    out = []
    # 1. the result
    if card["winner"] in ("home", "away"):
        W, L = (H, A) if card["winner"] == "home" else (A, H)
        t = f"{W['name']} beat {L['name']} {W['score']:,.2f} to {L['score']:,.2f}, a margin of {card['margin']:,.2f}."
        if ctx["games"] > 1:
            t += f" That was the {ordinal(_rank(card['margin'], ctx['margins']))}-largest margin of the week's {ctx['games']} games."
        if ctx["teams"] > 1:
            rw, rl = _rank(W["score"], ctx["order"]), _rank(L["score"], ctx["order"])
            t += (f" {poss(W['name'])} score was {'the best in the league' if rw == 1 else 'the ' + ordinal(rw) + '-best'} "
                  f"of {ctx['teams']} teams this week; {poss(L['name'])} ranked {ordinal(rl)}.")
        out.append({"lead": "The result", "text": t})
    else:
        out.append({"lead": "The result", "text": f"{H['name']} and {A['name']} tied at {H['score']:,.2f}."})
    # 2. how it was won
    board = card["board"]
    if board and card["winner"] in ("home", "away"):
        W, L = (H, A) if card["winner"] == "home" else (A, H)
        sign = 1 if card["winner"] == "home" else -1
        mine = sorted((b for b in board if b["edge"] * sign > 0), key=lambda b: -abs(b["edge"]))
        theirs = sorted((b for b in board if b["edge"] * sign < 0), key=lambda b: -abs(b["edge"]))
        t = f"{W['name']} won {len(mine)} of {len(board)} position groups"
        if mine:
            t += ", led by " + ", ".join(f"{b['grp']} (+{abs(b['edge']):,.2f})" for b in mine[:3])
        t += "."
        if theirs:
            t += f" {L['name']} led " + " and ".join(f"{b['grp']} by {abs(b['edge']):,.2f}" for b in theirs[:2]) + "."
        out.append({"lead": "How it was won", "text": t})
    # 3. the stars
    pl = card["players"]
    if card["players_basis"] == "actual" and (pl["home"] or pl["away"]):
        bits = []
        for s_, who in ((A, "away"), (H, "home")):
            if pl[who]:
                p = pl[who][0]
                bits.append(f"{p['name']} ({p['position']}) led {s_['name']} with {p['value']:,.2f}, {_pct(p['value'], s_['score'])} of the team's total")
        allp = [(p["value"], p["name"]) for who in ("home", "away") for p in pl[who]]
        t = "; ".join(bits) + "."
        deeper = [f"{s_['name']}: " + ", ".join(f"{p['name']} {p['value']:,.2f}" for p in pl[who][1:3])
                  for s_, who in ((A, "away"), (H, "home")) if len(pl[who]) > 1]
        if deeper:
            t += " Next best: " + "; ".join(deeper) + "."
        if allp:
            t += f" The best single score of the game was {max(allp)[1]}'s {max(allp)[0]:,.2f}."
        out.append({"lead": "The stars", "text": t})
    # 4. the bench
    if all(s_["opt"] is not None for s_ in (H, A)):
        left = {"home": H["opt"] - H["score"], "away": A["opt"] - A["score"]}
        t = (f"{A['name']} left {left['away']:,.2f} points on the bench (best possible lineup {A['opt']:,.2f}, {_pct(A['score'], A['opt'])} captured); "
             f"{H['name']} left {left['home']:,.2f} ({H['opt']:,.2f}, {_pct(H['score'], H['opt'])}).")
        sitters = []
        for s_, who in ((A, "away"), (H, "home")):
            b = card.get("bench", {}).get(who) or {}
            if b.get("score") is not None and b.get("name"):
                sitters.append(f"{b['name']}{' (' + b['position'] + ')' if b.get('position') else ''} for {s_['name']} ({b['score']:,.2f})")
        if sitters:
            t += " The best scorer on each bench: " + " and ".join(sitters) + "."
        if card["winner"] in ("home", "away"):
            W, L = (H, A) if card["winner"] == "home" else (A, H)
            if L["opt"] > W["score"]:
                t += f" With a perfect lineup {L['name']} would have won ({L['opt']:,.2f} to {W['score']:,.2f})."
            else:
                t += f" Even a perfect lineup ({L['opt']:,.2f}) would not have changed the result."
        out.append({"lead": "The bench", "text": t})
    # 5. the series
    sa = _series_after(card)
    if sa:
        t = sa[4]
        last = card["series"]["last"]
        if last and card["series"]["meetings"]:
            t += f" The previous meeting was {last['season']} week {last['week']}: {H['abbrev']} {last['home_score']:,.2f}, {A['abbrev']} {last['away_score']:,.2f}."
        out.append({"lead": "The series", "text": t})
    # 6. what is next
    nxt = _next_games(conn, card)
    if nxt:
        out.append({"lead": "Next", "text": nxt})
    return out


def _next_games(conn, card):
    """Next week's opponents for both teams, when the next week's pairings are in the mart."""
    rows = conn.execute("""SELECT home_id, away_id, home_name, away_name FROM mart_matchup_card
                           WHERE league_id = ? AND season = ? AND week = ?""",
                        (card["league_id"], card["season"], card["week"] + 1)).fetchall()
    if not rows:
        return None
    parts = []
    for s_ in (card["away"], card["home"]):
        opp = [r["away_name"] if r["home_id"] == s_["id"] else r["home_name"] for r in rows if s_["id"] in (r["home_id"], r["away_id"])]
        if opp:
            parts.append(f"{s_['name']} play " + " and ".join(opp))
    return f"In week {card['week'] + 1}, " + "; ".join(parts) + "." if parts else None


def _rank_text(value, order):
    """'1st', 'tied for 1st' ... of a value in a descending list (ties share a rank)."""
    r = _rank(value, order)
    ties = sum(1 for v in order if abs(v - value) <= 1e-9)
    return f"tied for {ordinal(r)}" if ties > 1 else ordinal(r)


def pre_context(conn, card) -> dict:
    """Where every team stands going into the week: win percentage, points for (every game counts, as in the league's own
    standings) and lineup efficiency (points for / best-possible-lineup points over the same games), from the mart's
    completed-weeks figures. Ranked inside the team's own conference when the mart knows it, else across the league.
    Empty when nobody has played yet."""
    rows = conn.execute("""SELECT * FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ?""",
                        (card["league_id"], card["season"], card["week"])).fetchall()
    team = {}
    for r in rows:
        for who in ("home", "away"):
            w, l, t = r[f"{who}_w"], r[f"{who}_l"], r[f"{who}_t"]
            opt = r[f"{who}_opt_pf"]
            team[r[f"{who}_id"]] = {"wp": (w + 0.5 * t) / (w + l + t) if (w + l + t) else None, "pf": r[f"{who}_pf"], "n": w + l + t,
                                    "eff": (r[f"{who}_pf"] / opt) if opt else None, "conf": r[f"{who}_conference"]}
    played = {k: v for k, v in team.items() if v["n"]}

    def pool(conf):
        """the teams a team is compared with: its conference when known, else the whole league"""
        return [v for v in played.values() if v["conf"] == conf] if conf else list(played.values())
    return {"teams": len(team), "by_team": team, "any_played": bool(played), "pool": pool}


def preview_paragraphs(conn, card) -> list:
    if card["state"] == "FINAL":
        return []
    H, A = card["home"], card["away"]
    out = []
    # 1. the matchup
    t = (f"{A['name']} ({A['w']}-{A['l']}{'-' + str(A['t']) if A['t'] else ''}) visit {H['name']} "
         f"({H['w']}-{H['l']}{'-' + str(H['t']) if H['t'] else ''}).")
    if card["rivalry"]:
        t += " It is a division game."
    if H["proj"] is not None and A["proj"] is not None:
        gap = abs(H["proj"] - A["proj"])
        fav = H if H["proj"] > A["proj"] else A
        other = A if fav is H else H   # the favourite's total FIRST: "(1,389.5 to 1,371.1)" reads as favourite to underdog
        t += f" The projections have {fav['name']} ahead by {gap:,.2f} points ({fav['proj']:,.2f} to {other['proj']:,.2f})"
        if card["win_prob"]:
            t += f", a {max(card['win_prob'].values()) * 100:.0f}% edge on v1's model"
        t += "."
    out.append({"lead": "The matchup", "text": t})
    # 2. why it is the featured game
    pk = card.get("pick")
    if card.get("featured") and pk:
        qh, qa = pk["quality_home"], pk["quality_away"]
        t = f"It ranks first of {pk['of']} games on the picker's score. " if pk["of"] > 1 else ""
        t += (f"Both teams rate highly ({qa:.2f} and {qh:.2f} on its 0-to-1 scale)" if min(qh, qa) > 0.5
              else f"The teams rate {qa:.2f} and {qh:.2f} on its 0-to-1 scale")
        if pk["closeness"] is not None and H["proj"] is not None and A["proj"] is not None:
            gap, total = abs(H["proj"] - A["proj"]), H["proj"] + A["proj"]
            t += f", and their projected totals are only {gap:,.2f} points apart, {gap / total * 100:.1f}% of the combined {total:,.2f}"
        out.append({"lead": "Why this game", "text": t + "."})
    # 3. the stakes: where both teams stand in the league
    ctx = pre_context(conn, card)
    if ctx["any_played"] and ctx["teams"] > 1:
        bits = []
        for s_ in (A, H):
            me = ctx["by_team"].get(s_["id"])
            if not me or not me["n"]:
                continue
            peers = ctx["pool"](me["conf"])
            scope = f"the {me['conf']}" if me["conf"] else "the league"
            rank = lambda key: _rank_text(me[key], sorted((v[key] for v in peers if v[key] is not None), reverse=True))
            bit = (f"{s_['name']} are {s_['w']}-{s_['l']}{'-' + str(s_['t']) if s_['t'] else ''} "
                   f"({rank('wp')} of {len(peers)} in {scope} by record) with {me['pf']:,.2f} points for ({rank('pf')} in {scope})")
            if me["eff"] is not None:
                bit += f" and a lineup efficiency of {me['eff'] * 100:.2f}% ({rank('eff')} in {scope})"
            bits.append(bit)
        if bits:
            out.append({"lead": "The stakes", "text": "; ".join(bits) + "."})
    # 4. the position battles
    board = card["board"]
    if board and card["board_basis"] == "projected":
        homes = sorted((b for b in board if b["edge"] > 0), key=lambda b: -b["edge"])
        aways = sorted((b for b in board if b["edge"] < 0), key=lambda b: b["edge"])
        bits = []
        if homes:
            bits.append(f"{H['name']} lead " + ", ".join(f"{b['grp']} (+{b['edge']:,.2f})" for b in homes[:3]))
        if aways:
            bits.append(f"{A['name']} lead " + ", ".join(f"{b['grp']} (+{abs(b['edge']):,.2f})" for b in aways[:3]))
        text = "; ".join(bits) + "."
        top = max(board, key=lambda b: abs(b["edge"]))
        text += f" The biggest gap is {top['grp']}, where {(H if top['edge'] > 0 else A)['name']} lead by {abs(top['edge']):,.2f}."
        out.append({"lead": "Position battles", "text": text})
    # 5. players to watch
    pl = card["players"]
    if card["players_basis"] == "projected" and (pl["home"] or pl["away"]):
        bits = [f"{s_['name']}: " + ", ".join(f"{p['name']} ({p['position']}) {p['value']:,.2f}" for p in pl[who])
                for s_, who in ((A, "away"), (H, "home")) if pl[who]]
        out.append({"lead": "Players to watch", "text": "; ".join(bits) + "."})
    # 6. the series
    s = card["series"]
    if s["meetings"]:
        lead = (f"{H['name']} lead {s['home_wins']}-{s['away_wins']}" if s["home_wins"] > s["away_wins"]
                else f"{A['name']} lead {s['away_wins']}-{s['home_wins']}" if s["away_wins"] > s["home_wins"]
                else f"The series is tied {s['home_wins']}-{s['away_wins']}")
        t = f"{lead} across {s['meetings']} regular-season meetings."
        if s["last"]:
            t += f" Last meeting: {s['last']['season']} week {s['last']['week']}, {H['abbrev']} {s['last']['home_score']:,.2f} to {A['abbrev']} {s['last']['away_score']:,.2f}."
        out.append({"lead": "The series", "text": t})
    return out


def paragraphs(conn, card) -> list:
    return recap_paragraphs(conn, card) if card["state"] == "FINAL" else preview_paragraphs(conn, card)


def to_markdown(paras, limit: int = 1900) -> str:
    """Discord markdown: '**Lead.** text' paragraphs, blank-line separated. If it will not fit, the LAST paragraphs are dropped
    (the result, how it was won and the stars are the last to go); a single paragraph is cut at a sentence, never mid-word."""
    def fmt(ps):
        return "\n\n".join(f"**{p['lead']}.** {p['text']}" for p in ps)
    ps = list(paras)
    while len(ps) > 1 and len(fmt(ps)) > limit:
        ps.pop()
    text = fmt(ps)
    if len(text) > limit:   # one paragraph is still too long: end at the last full sentence that fits
        cut = text[:limit]
        i = cut.rfind(". ")
        text = cut[:i + 1] if i > 0 else cut[:limit - 1].rstrip() + "…"
    return text
