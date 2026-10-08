"""The Wednesday choice: the picker's best games for a week, each with its pros and cons, so a person can choose which one
becomes the Matchup of the Week. Reads mart_matchup_card ONLY (through the picker). Every pro and con is a plain statement of
a number the picker already used or the card already shows; nothing here is a new model.

How the picker decides (fdb/matchup_pick.py, v1's selector):
  score = 0.45 * the weaker team's quality + 0.25 * closeness + 0.10 * size + 0.10 if both teams are good (> 0.5)
          - 0.40 * the gap between the two teams' qualities
  quality   a team's record, blended toward its prior (last season's results and this week's roster strength) while few
            games have been played
  closeness how near the two projected starter totals are
  size      how large the two totals are together, against the week's other games"""
from . import config, matchup_pick, matchup_weeks
from . import matchup_card as mc

DEFAULT_N = 5


def explain() -> str:
    return ("How the picker scores a game: 0.45 x the weaker team's quality + 0.25 x closeness of the two projected totals + "
            "0.10 x combined size + 0.10 if both teams rate above 0.5 - 0.40 x the quality gap between the teams. "
            "Quality is a team's win percentage blended toward its prior (last season's results and roster strength), "
            "which fades as games are played.")


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _rec(w, l, t):
    return f"{w}-{l}" + (f"-{t}" if t else "")


def _pros_cons(g, r, ranked_n, top_score, sizes) -> tuple:
    pros, cons = [], []
    qh, qa = g["quality_home"], g["quality_away"]
    weaker = r["home_name"] if qh < qa else r["away_name"]
    if g["both_good"]:
        pros.append(f"Both teams rate well ({qa:.2f} and {qh:.2f} on the 0-to-1 scale)")
    else:
        cons.append(f"{weaker} rates only {min(qh, qa):.2f} on the 0-to-1 scale")
    gap = abs(qh - qa)
    if gap >= 0.15:
        cons.append(f"Lopsided on paper: the teams' ratings are {gap:.2f} apart")
    elif gap <= 0.05:
        pros.append(f"Evenly matched on paper (ratings {gap:.2f} apart)")
    if g["closeness"] is not None:
        pg = abs(g["home_x"] - g["away_x"])
        comb = g["home_x"] + g["away_x"]
        if g["closeness"] >= 0.75:
            pros.append(f"Close projection: {pg:,.2f} points apart ({pg / comb * 100:.1f}% of {comb:,.2f} combined)")
        elif g["closeness"] < 0.5:
            cons.append(f"Projected to be one-sided: {pg:,.2f} points apart ({pg / comb * 100:.1f}% of {comb:,.2f} combined)")
        place = _ordinal(1 + sum(1 for s in sizes if s > comb))
        if g["size"] >= 0.8:
            pros.append(f"High scoring: {comb:,.2f} projected combined ({place} of {len(sizes)})")
        elif g["size"] <= 0.4:
            cons.append(f"Lower scoring: {comb:,.2f} projected combined ({place} of {len(sizes)})")
    wp = lambda w, l, t: (w + 0.5 * t) / (w + l + t) if (w + l + t) else None
    pa, ph = wp(r["away_w"], r["away_l"], r["away_t"]), wp(r["home_w"], r["home_l"], r["home_t"])
    if pa is not None and ph is not None:
        if min(pa, ph) >= 0.75:
            pros.append(f"Two of the league's best records ({_rec(r['away_w'], r['away_l'], r['away_t'])} and "
                        f"{_rec(r['home_w'], r['home_l'], r['home_t'])})")
        elif min(pa, ph) > 0.5:
            pros.append("Both teams have winning records")
        elif max(pa, ph) < 0.5:
            cons.append("Neither team has a winning record")
        elif min(pa, ph) < 0.5:
            cons.append(f"{r['away_name'] if pa < ph else r['home_name']} has a losing record")
    if r["is_division_rivalry"]:
        pros.append("A division game")
    if r["home_conference"] and r["home_conference"] == r["away_conference"]:
        pros.append(f"Both teams are in the {r['home_conference']}")
    elif r["home_conference"] and r["away_conference"]:
        cons.append(f"Interconference: {r['away_conference']} against {r['home_conference']}")
    if r["series_meetings"]:
        hw, aw = r["series_home_wins"], r["series_away_wins"]
        lead = (f"{r['home_abbrev']} lead {hw}-{aw}" if hw > aw else f"{r['away_abbrev']} lead {aw}-{hw}" if aw > hw
                else f"level at {hw}-{aw}")
        pros.append(f"Series history: {lead} over {r['series_meetings']} meetings")
    else:
        cons.append("No series history (first meeting)")
    if g["rank"] > 1:
        cons.append(f"The picker ranks it {g['rank']} of {ranked_n} (score {g['score']:.3f} against {top_score:.3f} for the top game)")
    else:
        pros.append(f"The picker's top game (score {g['score']:.3f})")
    return pros, cons


def candidates(conn, league, season, week, n=DEFAULT_N, include=()) -> list:
    """The top n games by the picker plus any `include`d id pairs, each with pros and cons."""
    p = matchup_pick.pick(conn, league, season, week)
    ranked = p["ranked"]
    if not ranked:
        return []
    rows = {(r["home_id"], r["away_id"]): r for r in conn.execute(
        "SELECT * FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ?", (league, season, week))}
    sizes = [g["home_x"] + g["away_x"] for g in ranked if g["home_x"] is not None]
    chosen = list(ranked[:n])
    for pair in include:
        for g in ranked:
            if {g["home_id"], g["away_id"]} == set(pair) and g not in chosen:
                chosen.append(g)
    out = []
    for g in sorted(chosen, key=lambda x: x["rank"]):
        r = rows[(g["home_id"], g["away_id"])]
        pros, cons = _pros_cons(g, r, len(ranked), ranked[0]["score"], sizes)
        out.append({"rank": g["rank"], "home_id": g["home_id"], "away_id": g["away_id"], "home_name": r["home_name"],
                    "away_name": r["away_name"], "score": g["score"],
                    "records": f"{_rec(r['away_w'], r['away_l'], r['away_t'])} ({r['away_abbrev']}) at "
                               f"{_rec(r['home_w'], r['home_l'], r['home_t'])} ({r['home_abbrev']})", "basis": p["basis"], "pros": pros, "cons": cons})
    return out


def to_markdown(info, cands) -> str:
    lines = [f"# Matchup of the Week: choices for {info['league_name']} {info['season']} week {info['week']}", "",
             explain(), "",
             "Post your choice with:  `python -m fdb post --mode preview --game HOME_ID:AWAY_ID --send`", ""]
    for c in cands:
        lines += [f"## {c['rank']}. {c['away_name']} at {c['home_name']}  (`--game {c['home_id']}:{c['away_id']}`)",
                  f"Records {c['records']}. Picker score {c['score']:.3f}, ranked on {c['basis']}.", ""]
        lines += [f"- Pro: {x}" for x in c["pros"]] + [f"- Con: {x}" for x in c["cons"]] + [""]
    return "\n".join(lines)


def build(conn, league="30590", n=DEFAULT_N, include=()):
    """(markdown, path, target) for the next week's choices, or (None, None, target) when there is nothing to choose."""
    t = matchup_weeks.preview_target(conn, league)
    if not t.get("season") or not t.get("week"):
        return None, None, t
    cands = candidates(conn, t["league"], t["season"], t["week"], n, include)
    if not cands:
        return None, None, t
    info = {"league_name": mc.league_name(conn, t["league"]), "season": t["season"], "week": t["week"]}
    path = config.ROOT / "data" / "cards" / f"{t['league']}_{t['season']}_wk{t['week']:02d}_choices.md"
    return to_markdown(info, cands), path, t


def write(conn, league="30590", n=DEFAULT_N):
    """Write the next week's choices file and return (path, week), or None when there is nothing to choose. Never posts."""
    text, path, t = build(conn, league, n)
    if text is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, t["week"]


def run(conn, league="30590", n=DEFAULT_N, include=(), say=print) -> int:
    text, path, t = build(conn, league, n, include)
    if text is None:
        say(f"choices: nothing to choose: {t.get('reason')}")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if not t.get("ready"):
        say(f"choices: note: {t.get('reason')}")
    say(text)
    say(f"choices: written to {path}")
    return 0


def parse_pair(text):
    """'0024:0023' -> ('0024', '0023') (either order is accepted by the callers), or None when it is not two ids"""
    parts = [x.strip() for x in str(text).split(":")]
    return tuple(parts) if len(parts) == 2 and all(parts) and parts[0] != parts[1] else None
