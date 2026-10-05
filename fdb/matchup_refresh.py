"""`fdb matchup-refresh`: re-fetch what a Matchup of the Week PREVIEW is built from, rebuild the card data, and say whether a
recap and a preview are ready. For the two moments the weekly job (Wednesday 05:00) cannot cover on its own:
  * MFL had not set the new week's lineups yet (a franchise without a lineup has no projected total), and
  * Thursday morning before kickoff, when injuries have moved the projections since Wednesday.
It runs the weekly job's own loader runner (fdb/weekly.py run_loader) for the three pre-game feeds, in the same order, then the
matchup builder. It posts nothing and sends nothing; `fdb post` is the only thing that does, and only with --send.

A refresh made AFTER the week has kicked off is harmless but useless for a preview: the card uses, per week, the LAST projection
snapshot taken before the first kickoff, so a later one is kept in history and not used. The command says so."""
from . import matchup, matchup_weeks, weekly

LOADERS = ("mfl.upcoming_games", "mfl.upcoming_lineups", "mfl.projected_scores")


def run(conn, league: str = "30590") -> int:
    rc = 0
    for lid in LOADERS:
        d = weekly.run_loader(conn, lid)
        line = f"{lid}: fetched {d['fetched']}, cached {d['cached']}, loaded {d['loaded']}"
        if d["failures"]:
            line += f", FAILED {len(d['failures'])}: " + "; ".join(d["failures"][:2])
        print(line)
        rc = rc or d["rc"]
    res = matchup.build(conn)
    print(f"matchup.build: {res['summary']}" + (f" FAILED {res['failures'][:2]}" if res["failures"] else ""))
    rc = rc or (1 if res["failures"] else 0)
    for fn in (matchup_weeks.recap_target, matchup_weeks.preview_target):
        t = fn(conn, league)
        state = "ready" if t["ready"] else "NOT ready"
        week = f"week {t['week']}" if t["week"] else "no week"
        print(f"{t['mode']}: {week} {state}" + (f": {t['reason']}" if t["reason"] else ""))
        if t["mode"] == "preview" and t["state"] == "LIVE":
            print("preview: this refresh was made after kickoff; its projections will NOT be used (the last pre-kickoff snapshot is)")
    return rc
