"""Which week a Matchup of the Week post is about, for a recap and for a preview. Reads mart_matchup_card ONLY.

v1 took ONE "current week" (`war_engine._detect_current_week()`) for BOTH modes, so a Monday-morning recap targeted the
week that had not been played (its post said "Week 4 recap" with 0.00 scores and FINAL). Here they are different
questions with different answers:

  recap_target    the LATEST week whose results are loaded (every game FINAL). Until the weekly job has loaded a finished
                  week (Monday night settles Wednesday 00:15 ET, the job runs 05:00) the answer is still the previous
                  week, and `waiting_for` names the week that is in progress, so a job can see why nothing new is ready.
  preview_target  the EARLIEST week that has not kicked off (PREVIEW). A week that has already kicked off can no longer be
                  previewed: `ready` is False and the reason says so. It also reports whether a pre-kickoff projection was
                  captured, because a preview without one has no projected panels (the caller decides whether to post).

Both return a dict and never raise: {"ready", "league", "season", "week", "state", "reason", "featured", ...}. A target
that is not ready still says what it found, so a job can log it. Neither function posts anything or writes anything.
Fantasy playoff weeks are weeks like any other here; `is_playoff` is reported for the caller to decide."""
from . import matchup_card as mc
from . import matchup_pick


def _week_status(conn, league, season):
    """{week: {"state": FINAL | LIVE | PREVIEW, "games": n, "playoff": bool, "projected": bool, "snapshot": bool,
    "unprojected": games with a side that has no projected total}} for one league-season. A week is FINAL only if EVERY game is
    FINAL; PREVIEW only if every game is. `projected` = every game has both totals; `snapshot` = a pre-kickoff projection
    snapshot exists at all (so an unprojected game then means a LINEUP is missing, not a projection)."""
    out = {}
    for r in conn.execute("""SELECT week, state, is_playoff, home_proj, away_proj, proj_snapshot_at, home_live_score, away_live_score
                             FROM mart_matchup_card
                             WHERE league_id = ? AND season = ?""", (league, season)):
        w = out.setdefault(r["week"], {"states": set(), "games": 0, "playoff": False, "snapshot": False, "unprojected": 0, "unscored": 0})
        w["states"].add(r["state"])
        w["games"] += 1
        w["playoff"] = w["playoff"] or bool(r["is_playoff"])
        w["snapshot"] = w["snapshot"] or r["proj_snapshot_at"] is not None
        w["unprojected"] += r["home_proj"] is None or r["away_proj"] is None
        w["unscored"] += r["home_live_score"] is None or r["away_live_score"] is None
    for w in out.values():
        s = w.pop("states")
        w["state"] = "FINAL" if s == {"FINAL"} else "PREVIEW" if s == {"PREVIEW"} else "LIVE"
        w["projected"] = w["unprojected"] == 0
    return out


def _scope(conn, league, season):
    """(league, season, problem). A league or season that is NAMED but has no data is a problem, never silently replaced by
    another (a job asking for league 55757 must not get 30590's card). Only an unnamed league or season gets a default."""
    held = [x["league_id"] for x in mc.leagues(conn)]
    if league is not None and str(league) not in held:
        return str(league), season, f"no matchup data for league {league}"
    league, default_season, _ = mc.resolve(conn, league, None, None)
    if league is None:
        return None, None, "no matchup data yet"
    if season is not None and season not in mc.seasons(conn, league):
        return league, season, f"no matchup data for league {league} season {season}"
    return league, (season if season is not None else default_season), None


def _featured(conn, league, season, week):
    p = matchup_pick.pick(conn, league, season, week)
    f = p["featured"]
    return None if f is None else {"home_id": f["home_id"], "away_id": f["away_id"], "basis": p["basis"], "score": f["score"]}


def _unprojected_reason(w):
    """Why a PREVIEW week is not fully projected, or None when it is."""
    if w["projected"]:
        return None
    if not w["snapshot"]:
        return "no projection was captured before kickoff, so the preview has no projected panels or win probability"
    return (f"{w['unprojected']} of {w['games']} games have a side with no lineup yet, so their projected totals cannot be "
            "computed (MFL sets a new week's lineups as it becomes the current week); try again later")


def recap_target(conn, league=None, season=None) -> dict:
    league, season, problem = _scope(conn, league, season)
    base = {"mode": "recap", "league": league, "season": season, "week": None, "state": None, "ready": False,
            "reason": None, "waiting_for": None, "is_playoff": None, "featured": None}
    if problem:
        return {**base, "reason": problem}
    weeks = _week_status(conn, league, season)
    final = [w for w, v in weeks.items() if v["state"] == "FINAL"]
    ahead = sorted(w for w, v in weeks.items() if v["state"] == "LIVE" and (not final or w > max(final)))
    if not final:
        return {**base, "reason": f"no week of {season} has its results loaded yet",
                "waiting_for": ahead[0] if ahead else None}
    week = max(final)
    return {**base, "week": week, "state": "FINAL", "ready": True, "is_playoff": weeks[week]["playoff"],
            "waiting_for": ahead[0] if ahead else None,
            "reason": (f"week {ahead[0]} is in progress or waiting for its results; its recap is not ready" if ahead else None),
            "featured": _featured(conn, league, season, week)}


def live_target(conn, league=None, season=None) -> dict:
    """The week IN PROGRESS (its first kickoff has passed and its results are not loaded), for the "so far" card. Ready only
    when every game of that week has live scores loaded (`fdb live-refresh` fetches them); never guessed from projections."""
    league, season, problem = _scope(conn, league, season)
    base = {"mode": "live", "league": league, "season": season, "week": None, "state": None, "ready": False,
            "reason": None, "projected": None, "is_playoff": None, "featured": None}
    if problem:
        return {**base, "reason": problem}
    weeks = _week_status(conn, league, season)
    live = sorted(w for w, v in weeks.items() if v["state"] == "LIVE")
    if not live:
        return {**base, "reason": "no week is in progress (a week is live from its first kickoff until its results are loaded)"}
    week = live[0]
    v = weeks[week]
    ready = v["unscored"] == 0
    return {**base, "week": week, "state": "LIVE", "ready": ready, "projected": v["projected"], "is_playoff": v["playoff"],
            "featured": _featured(conn, league, season, week),
            "reason": None if ready else f"{v['unscored']} of {v['games']} games have no live scores loaded yet; run `fdb live-refresh`"}


def preview_target(conn, league=None, season=None) -> dict:
    league, season, problem = _scope(conn, league, season)
    base = {"mode": "preview", "league": league, "season": season, "week": None, "state": None, "ready": False,
            "reason": None, "projected": None, "is_playoff": None, "featured": None}
    if problem:
        return {**base, "reason": problem}
    weeks = _week_status(conn, league, season)
    upcoming = sorted(w for w, v in weeks.items() if v["state"] == "PREVIEW")
    if upcoming:
        week = upcoming[0]
        return {**base, "week": week, "state": "PREVIEW", "ready": True, "projected": weeks[week]["projected"],
                "is_playoff": weeks[week]["playoff"], "featured": _featured(conn, league, season, week),
                "reason": _unprojected_reason(weeks[week])}
    live = sorted(w for w, v in weeks.items() if v["state"] == "LIVE")
    if live:
        week = live[-1]
        return {**base, "week": week, "state": "LIVE", "projected": weeks[week]["projected"], "is_playoff": weeks[week]["playoff"],
                "featured": _featured(conn, league, season, week),
                "reason": f"week {week} has already kicked off; a preview has to be rendered before kickoff"}
    return {**base, "reason": "no upcoming week in the data (the season is over, or the weekly job has not fetched the next week)"}
