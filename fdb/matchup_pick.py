"""The featured-game picker ("Matchup of the Week"): a port of v1's `pick_matchup` scorer (football_db/app/scouting.py),
reading mart_matchup_card ONLY. Turon chose "the picked game" = v1's selector.

For every game in a league-week:
  quality(team) = w * (wins / games) + (1 - w) * prior,   w = games / (games + K)        (K = 6: games at which the live
                  record weighs the same as the prior)
  prior         = 0.6 * pedigree + 0.4 * roster-strength rank   (roster rank only, when the team has no pedigree)
  pedigree      = last season's results: 0.7 * (0.5 * win% rank + 0.5 * points-for rank) + 0.3 * playoff result
                  (champion 1.0, finalist 0.85), all min-max normalised across the league
  closeness     = 1 - min(|home - away| / combined * 6, 1)           (of the two teams' projected starter totals)
  size          = (combined - lowest combined of the week) / range of combined
  both_good     = 0.10 if both teams' quality > 0.5
  score         = 0.45 * min(quality) + 0.25 * closeness + 0.10 * size + both_good - 0.40 * |quality gap|
The highest score is featured.

Differences from v1, each deliberate and stated on the page:
  * v1's "strength" and projections come from MFL's projectedScores at run time. Here they come from the last snapshot
    taken BEFORE the week's first kickoff (the mart's *_proj / *_strength), so a preview and its recap pick the same game.
  * last season's win% and points-for come from the mart's completed games (regular season, each week's points counted
    once), not MFL's standings (whose points-for counts every game and the playoffs). Ranks, not totals, are used, so the
    difference is small; it is not zero.
  * `basis`: with no pre-kickoff projection a FINAL week is ranked from what happened (starters' actual scores as the
    projection, the whole lineup's actual scores as the strength); with neither, from records and pedigree alone (the
    closeness and size terms are dropped). Nothing is guessed, and the basis is returned with the pick."""
K_SHRINK = 6.0
W_QUALITY, W_CLOSE, W_SIZE, W_BOTH, W_GAP = 0.45, 0.25, 0.10, 0.10, 0.40
PRIOR_PEDIGREE, PRIOR_STRENGTH = 0.6, 0.4
CLOSE_SCALE = 6.0


def _norm(x, values):
    lo, hi = min(values), max(values)
    return (x - lo) / ((hi - lo) or 1)


def pedigree(games) -> dict:
    """{franchise id: 0..1} from a prior season's FINAL games: dicts with home_id, away_id, week, home_score, away_score,
    is_playoff. Empty in, empty out (a league's first season has no pedigree)."""
    wins, losses, pf, by_week = {}, {}, {}, {}
    for g in games:
        if g["home_score"] is None or g["away_score"] is None:
            continue
        if g["is_playoff"]:
            by_week.setdefault(g["week"], []).append(g)
            continue
        for me, opp, a, b in ((g["home_id"], g["away_id"], g["home_score"], g["away_score"]),
                              (g["away_id"], g["home_id"], g["away_score"], g["home_score"])):
            wins[me] = wins.get(me, 0) + (a > b)
            losses[me] = losses.get(me, 0) + (a < b)
            pf.setdefault(me, {})[g["week"]] = a   # a week's points once
    ids = sorted(pf)
    if not ids:
        return {}
    wp = {f: wins.get(f, 0) / max(wins.get(f, 0) + losses.get(f, 0), 1) for f in ids}
    pts = {f: sum(pf[f].values()) for f in ids}
    champ = finalist = None
    for wk in sorted(by_week, reverse=True):   # the latest week with exactly one game is the final
        if len(by_week[wk]) == 1:
            g = by_week[wk][0]
            if g["home_score"] != g["away_score"]:
                champ, finalist = ((g["home_id"], g["away_id"]) if g["home_score"] > g["away_score"]
                                   else (g["away_id"], g["home_id"]))
            break
    raw = {}
    for f in ids:
        reg = 0.5 * _norm(wp[f], list(wp.values())) + 0.5 * _norm(pts[f], list(pts.values()))
        bonus = 1.0 if f == champ else 0.85 if f == finalist else 0.0
        raw[f] = 0.7 * reg + 0.3 * bonus
    return {f: _norm(raw[f], list(raw.values())) for f in ids}


def rank_games(games, ped, basis, k=K_SHRINK) -> list:
    """games: dicts with home_id, away_id, home_w, home_l, away_w, away_l and, per basis, home_x / away_x (the projected
    or actual starters' total) and home_strength / away_strength. -> the same games scored, best first."""
    if not games:
        return []
    sides = [(g["home_id"], g["home_w"], g["home_l"], g["home_strength"]) for g in games] + \
            [(g["away_id"], g["away_w"], g["away_l"], g["away_strength"]) for g in games]
    use_proj = basis in ("projection", "actual")
    strengths = [s[3] for s in sides if s[3] is not None] if use_proj else []
    smin, srange = (min(strengths), (max(strengths) - min(strengths)) or 1) if strengths else (0.0, 1)
    combs = [g["home_x"] + g["away_x"] for g in games] if use_proj else []
    cmin, crange = (min(combs), (max(combs) - min(combs)) or 1) if combs else (0.0, 1)

    def quality(fid, w, l, strength):
        rn = (strength - smin) / srange if (use_proj and strength is not None) else None
        pd = ped.get(fid)
        if pd is not None and rn is not None:
            prior = PRIOR_PEDIGREE * pd + PRIOR_STRENGTH * rn
        else:
            prior = pd if pd is not None else (rn if rn is not None else 0.5)
        g = w + l
        weight = g / (g + k)
        return weight * (w / (g or 1)) + (1 - weight) * prior

    out = []
    for g in games:
        qa = quality(g["home_id"], g["home_w"], g["home_l"], g["home_strength"])
        qb = quality(g["away_id"], g["away_w"], g["away_l"], g["away_strength"])
        both = W_BOTH if min(qa, qb) > 0.5 else 0.0
        if use_proj:
            comb = g["home_x"] + g["away_x"]
            comp = 1 - min(abs(g["home_x"] - g["away_x"]) / max(comb, 1) * CLOSE_SCALE, 1)
            size = (comb - cmin) / crange
        else:
            comp = size = None
        score = (min(qa, qb) * W_QUALITY + (comp or 0.0) * W_CLOSE + (size or 0.0) * W_SIZE + both - W_GAP * abs(qa - qb))
        out.append({**g, "quality_home": qa, "quality_away": qb, "closeness": comp, "size": size, "both_good": both,
                    "score": score, "basis": basis})
    out.sort(key=lambda x: (-x["score"], x["home_id"], x["away_id"]))
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return out


def pick(conn, league, season, week, k=K_SHRINK) -> dict:
    """{"basis", "ranked": [...], "featured": the top game or None, "pedigree": bool}"""
    rows = [dict(r) for r in conn.execute("SELECT * FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ?",
                                          (league, season, week))]
    prior = [dict(r) for r in conn.execute(
        """SELECT home_id, away_id, week, home_score, away_score, is_playoff FROM mart_matchup_card
           WHERE league_id = ? AND season = ? AND state = 'FINAL'""", (league, season - 1))]
    ped = pedigree(prior)
    if not rows:
        return {"basis": None, "ranked": [], "featured": None, "pedigree": bool(ped)}
    have_proj = all(r["home_proj"] is not None and r["away_proj"] is not None and r["home_strength"] is not None
                    and r["away_strength"] is not None for r in rows)
    have_actual = all(r["state"] == "FINAL" and r["home_score"] is not None and r["away_score"] is not None
                      and r["home_roster_actual"] is not None and r["away_roster_actual"] is not None for r in rows)
    basis = "projection" if have_proj else "actual" if have_actual else "records"
    games = []
    for r in rows:
        g = {"home_id": r["home_id"], "away_id": r["away_id"], "home_w": r["home_w"], "home_l": r["home_l"],
             "away_w": r["away_w"], "away_l": r["away_l"], "home_strength": None, "away_strength": None,
             "home_x": None, "away_x": None}
        if basis == "projection":
            g.update(home_x=r["home_proj"], away_x=r["away_proj"], home_strength=r["home_strength"], away_strength=r["away_strength"])
        elif basis == "actual":
            g.update(home_x=r["home_score"], away_x=r["away_score"], home_strength=r["home_roster_actual"], away_strength=r["away_roster_actual"])
        games.append(g)
    ranked = rank_games(games, ped, basis, k)
    return {"basis": basis, "ranked": ranked, "featured": ranked[0] if ranked else None, "pedigree": bool(ped)}


BASIS_TEXT = {
    "projection": "pre-kickoff projections (v1's formula)",
    "actual": "what happened: no projection was captured before kickoff, so actual scores stand in for projections",
    "records": "records and last season's results only: no projection was captured before kickoff",
}
