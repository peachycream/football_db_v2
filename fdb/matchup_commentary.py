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
            t += ", led by " + ", ".join(f"{b['grp']} (+{abs(b['edge']):,.1f})" for b in mine[:3])
        t += "."
        if theirs:
            t += f" {L['name']} led " + " and ".join(f"{b['grp']} by {abs(b['edge']):,.1f}" for b in theirs[:2]) + "."
        out.append({"lead": "How it was won", "text": t})
    # 3. the stars
    pl = card["players"]
    if card["players_basis"] == "actual" and (pl["home"] or pl["away"]):
        bits = []
        for s_, who in ((A, "away"), (H, "home")):
            if pl[who]:
                p = pl[who][0]
                bits.append(f"{p['name']} ({p['position']}) led {s_['name']} with {p['value']:,.1f}, {_pct(p['value'], s_['score'])} of the team's total")
        allp = [(p["value"], p["name"]) for who in ("home", "away") for p in pl[who]]
        t = "; ".join(bits) + "."
        deeper = [f"{s_['name']}: " + ", ".join(f"{p['name']} {p['value']:,.1f}" for p in pl[who][1:3])
                  for s_, who in ((A, "away"), (H, "home")) if len(pl[who]) > 1]
        if deeper:
            t += " Next best: " + "; ".join(deeper) + "."
        if allp:
            t += f" The best single score of the game was {max(allp)[1]}'s {max(allp)[0]:,.1f}."
        out.append({"lead": "The stars", "text": t})
    # 4. the bench
    if all(s_["opt"] is not None for s_ in (H, A)):
        left = {"home": H["opt"] - H["score"], "away": A["opt"] - A["score"]}
        t = (f"{A['name']} left {left['away']:,.1f} points on the bench (best possible lineup {A['opt']:,.1f}, {_pct(A['score'], A['opt'])} captured); "
             f"{H['name']} left {left['home']:,.1f} ({H['opt']:,.1f}, {_pct(H['score'], H['opt'])}).")
        sitters = []
        for s_, who in ((A, "away"), (H, "home")):
            b = card.get("bench", {}).get(who) or {}
            if b.get("score") is not None and b.get("name"):
                sitters.append(f"{b['name']}{' (' + b['position'] + ')' if b.get('position') else ''} for {s_['name']} ({b['score']:,.1f})")
        if sitters:
            t += " The best scorer on each bench: " + " and ".join(sitters) + "."
        if card["winner"] in ("home", "away"):
            W, L = (H, A) if card["winner"] == "home" else (A, H)
            if L["opt"] > W["score"]:
                t += f" With a perfect lineup {L['name']} would have won ({L['opt']:,.1f} to {W['score']:,.2f})."
            else:
                t += f" Even a perfect lineup ({L['opt']:,.1f}) would not have changed the result."
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


def preview_paragraphs(conn, card) -> list:
    if card["state"] == "FINAL":
        return []
    H, A = card["home"], card["away"]
    out = []
    t = (f"{A['name']} ({A['w']}-{A['l']}{'-' + str(A['t']) if A['t'] else ''}) visit {H['name']} "
         f"({H['w']}-{H['l']}{'-' + str(H['t']) if H['t'] else ''}).")
    if card["rivalry"]:
        t += " It is a division game."
    if H["proj"] is not None and A["proj"] is not None:
        gap = abs(H["proj"] - A["proj"])
        fav = H if H["proj"] > A["proj"] else A
        t += f" The projections have {fav['name']} ahead by {gap:,.1f} points ({H['proj']:,.1f} to {A['proj']:,.1f})"
        if card["win_prob"]:
            t += f", a {max(card['win_prob'].values()) * 100:.0f}% edge on v1's model"
        t += "."
    out.append({"lead": "The matchup", "text": t})
    board = card["board"]
    if board and card["board_basis"] == "projected":
        homes = sorted((b for b in board if b["edge"] > 0), key=lambda b: -b["edge"])
        aways = sorted((b for b in board if b["edge"] < 0), key=lambda b: b["edge"])
        bits = []
        if homes:
            bits.append(f"{H['name']} lead " + ", ".join(f"{b['grp']} (+{b['edge']:,.1f})" for b in homes[:3]))
        if aways:
            bits.append(f"{A['name']} lead " + ", ".join(f"{b['grp']} (+{abs(b['edge']):,.1f})" for b in aways[:3]))
        out.append({"lead": "Position battles", "text": "; ".join(bits) + "."})
    pl = card["players"]
    if card["players_basis"] == "projected" and (pl["home"] or pl["away"]):
        bits = [f"{s_['name']}: " + ", ".join(f"{p['name']} ({p['position']}) {p['value']:,.1f}" for p in pl[who])
                for s_, who in ((A, "away"), (H, "home")) if pl[who]]
        out.append({"lead": "Players to watch", "text": "; ".join(bits) + "."})
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
