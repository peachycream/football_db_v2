"""Player-status alerts: which of MY rostered players changed status, pushed to my phone (Phase 12 + 13).

Reads only mart_roster_ownership (is_mine, every league on every platform loaded), mart_injury_nfl / _mfl / _espn and
core_schedule, joined on gsis_id. Keeps what it last told me in app_alert_state, so a status is announced once.

Decisions that are deliberate, each from a way this could mislead or flood:
  * The three feeds are never merged into one "status". An alert shows the NFL report's game designation and practice
    participation, MFL's own status, and ESPN's, as separate lines, because they are different claims.
  * A report week with NO rows in the NFL file means "not published yet" (the file holds weeks 1-4 until Wednesday's
    week-5 report arrives), never "everyone is healthy". The NFL part of the state is then carried forward untouched.
  * The first run is a silent baseline (`--seed`); `--send` refuses to run before one exists.
  * When the report week rolls over, last week's designations are not announced as "cleared"; only a new actionable
    designation is. (MFL's status is not week-bound and is always compared.)
  * A push that fails keeps that player's PREVIOUS state, so the next run tries again. A failure is logged.
  * Nothing here sends unless `--send` is given. The default is a dry run with no network and no writes.

Game day (Phase 13): ESPN's entry is "game-day" when its own timestamp is within 3 hours before that player's kickoff
(measured: the active/inactive list posts 70-89 minutes before). A game-day entry reads ACTIVE or INACTIVE; an earlier
one keeps ESPN's plain word (OUT, QUESTIONABLE...). An INACTIVE nobody expected is the loudest alert there is; a
Questionable player turning ACTIVE is good news worth a push. Fifteen minutes before kickoff a player still listed
Questionable/Doubtful with no ACTIVE/INACTIVE from ESPN gets a one-time NOT CONFIRMED push (ledger: app_alert_final),
and says so if ESPN has posted nothing at all for his team. `--watch` polls ESPN only inside kickoff windows
(fdb/gameday.py).

Not here yet: news/RSS, lineup awareness (starters outrank bench), Yahoo/CBS rosters."""
import contextlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta

from . import config, gameday, notify, schedule
from .timeutil import parse_utc, utcnow

GAME_ACTIONABLE = ("Out", "Doubtful", "Questionable")
PRACTICE_SHORT = (("Did Not", "DNP"), ("Limited", "LP"), ("Full", "FP"))
PRACTICE_ACTIONABLE = ("DNP", "LP")
SLOT_SHOWN = {"roster": "", "starter": "starter", "bench": "bench", "taxi": "taxi", "ir": "IR"}
URGENT_GAME = ("Out", "Doubtful")
GAMEDAY_LOOKBACK = timedelta(hours=3)   # an ESPN entry this close to kickoff (or later) is a game-day entry
UNCERTAIN = ("QUESTIONABLE", "DOUBTFUL")
POLL_SECONDS = 120
FULL_REFRESH_EVERY = 10   # polls: the NFL file and MFL are slow feeds; ESPN is refreshed every poll
FEED_FAILS_BEFORE_PUSH = 3


def practice_short(s: str | None) -> str | None:
    for prefix, short in PRACTICE_SHORT:
        if s and s.startswith(prefix):
            return short
    return s or None


# ----------------------------------------------------------------- reading --
@dataclass
class Evaluation:
    season: int
    season_type: str
    week: int
    nfl_published: bool
    players: dict = field(default_factory=dict)   # gsis_id -> snapshot dict (see evaluate())
    feeds: dict = field(default_factory=dict)     # name -> raw fetched_at, for the staleness line
    espn_loaded: bool = False
    posted: dict = field(default_factory=dict)    # canonical team -> number of ESPN game-day entries
    games: list = field(default_factory=list)


def report_week(conn, season: int, now) -> tuple[str, int] | None:
    """The week whose injury report is the live one: the first week not yet COMPLETE per the schedule
    (a week completes 28 h after its last kickoff, i.e. Tuesday night, just before the next report)."""
    done = set(schedule.completed_weeks(conn, season, now))
    order = {"REG": 0, "POST": 1}
    weeks = sorted({(r[0], r[1]) for r in conn.execute("SELECT season_type, week FROM core_schedule WHERE season = ?", (season,))},
                   key=lambda k: (order[k[0]], k[1]))
    return next((k for k in weeks if k not in done), None)


def rostered(conn, season: int) -> dict:
    """gsis_id -> {name, position, team, leagues: [(league, slot)]} for MY franchises, current season. Players with no
    gsis_id (devy/college ids) cannot be matched to an NFL report and are not tracked here."""
    out: dict = {}
    for r in conn.execute("""SELECT o.gsis_id, o.league_name, o.slot, p.display_name, p.position, p.latest_team
                             FROM mart_roster_ownership o JOIN players p ON p.gsis_id = o.gsis_id
                             WHERE o.season = ? AND o.is_mine = 1 AND o.gsis_id IS NOT NULL
                             ORDER BY o.gsis_id, o.league_name, o.slot""", (season,)):
        d = out.setdefault(r["gsis_id"], {"name": r["display_name"], "position": r["position"], "team": r["latest_team"],
                                          "leagues": []})
        if (r["league_name"], r["slot"]) not in d["leagues"]:
            d["leagues"].append((r["league_name"], r["slot"]))
    return out


def _canon(conn, season: int) -> dict:
    """Every spelling of a team (ESPN's WSH, nflverse's WAS, a stale OAK) -> the one canonical name."""
    return {r[0]: r[1] for r in conn.execute("SELECT abbr, team FROM team_aliases WHERE ? BETWEEN season_from AND season_to", (season,))}


def espn_state(e: dict | None) -> str | None:
    """ESPN's entry as one word. Game-day: ACTIVE / INACTIVE, else ESPN's own status in capitals. Before game day an
    'Active' entry is no designation at all (None)."""
    if not e or not e.get("status"):
        return None
    s = e["status"]
    if e.get("gameday"):
        if s == "Active":
            return "ACTIVE"
        if s == "Out" and e.get("fantasy") == "INACTIVE":
            return "INACTIVE"
    return None if s == "Active" else s.upper()


def flagged_espn(state: str | None) -> bool:
    return state is not None and state != "ACTIVE"


def evaluate(conn, now=None) -> Evaluation | None:
    now = now or utcnow()
    season = schedule.current_season(conn, now)
    if season is None:
        return None
    wk = report_week(conn, season, now)
    if wk is None:   # season over
        return None
    st, week = wk
    nfl = {}
    for r in conn.execute("""SELECT gsis_id, game_status, game_injury, practice_status, practice_injury
                             FROM mart_injury_nfl WHERE season = ? AND season_type = ? AND week = ?
                             ORDER BY gsis_id, team DESC""", (season, st, week)):
        nfl[r["gsis_id"]] = r   # a traded player's second row replaces the first; deterministic by the ORDER BY
    published = bool(conn.execute("SELECT 1 FROM core_nflverse_injuries WHERE season = ? AND season_type = ? AND week = ?",
                                  (season, st, week)).fetchone())
    mfl = {r["gsis_id"]: r for r in conn.execute(
        "SELECT gsis_id, mfl_status, mfl_details, mfl_exp_return FROM mart_injury_mfl WHERE season = ? AND gsis_id IS NOT NULL",
        (season,))}
    espn = {r["gsis_id"]: r for r in conn.execute(
        "SELECT * FROM mart_injury_espn WHERE season = ? AND season_type = ? AND gsis_id IS NOT NULL", (season, st))}
    espn_loaded = bool(conn.execute("SELECT 1 FROM core_espn_injuries WHERE season = ? AND season_type = ?", (season, st)).fetchone())

    canon = _canon(conn, season)
    gs = gameday.games(conn, season, st, week)
    tg = gameday.by_team(gs)
    ev = Evaluation(season, st, week, published, espn_loaded=espn_loaded, games=gs)
    for gsis, info in rostered(conn, season).items():
        n, m, e = nfl.get(gsis), mfl.get(gsis), espn.get(gsis)
        team = canon.get((e["espn_team"] if e else None) or info["team"]) or canon.get(info["team"])
        g = tg.get(team)
        snap_game = ({"game_id": g.game_id, "kickoff": g.kickoff.isoformat(), "when": g.when(team), "team": team} if g else None)
        espn_snap = None
        if espn_loaded:
            espn_snap = {"status": e["espn_status"] if e else None, "fantasy": e["espn_fantasy_status"] if e else None,
                         "date": e["espn_date"] if e else None, "comment": (e["espn_comment"] or None) if e else None,
                         "injury": (e["espn_injury"] or None) if e else None,
                         "gameday": bool(e and g and parse_utc(e["espn_date"]) >= g.kickoff - GAMEDAY_LOOKBACK)}
        ev.players[gsis] = {
            **info,
            "game": snap_game,
            "nfl": ({"game": (n["game_status"] if n else None) or None,
                     "practice": practice_short(n["practice_status"]) if n else None,
                     "injury": ((n["game_injury"] or n["practice_injury"]) if n else None) or None} if published else None),
            "mfl": {"status": m["mfl_status"], "details": m["mfl_details"] or None, "exp_return": m["mfl_exp_return"] or None} if m else None,
            "espn": espn_snap,
        }
    if espn_loaded:   # how many game-day entries ESPN has for each team: 0 means "not posted yet", not "all healthy"
        for r in conn.execute("SELECT team, date FROM core_espn_injuries WHERE season = ? AND season_type = ?", (season, st)):
            t, g = canon.get(r["team"]), tg.get(canon.get(r["team"]))
            if g and parse_utc(r["date"]) >= g.kickoff - GAMEDAY_LOOKBACK:
                ev.posted[t] = ev.posted.get(t, 0) + 1
    for name, (src, ep) in (("nfl", ("nflverse", "injuries")), ("mfl", ("mfl", "injuries")), ("espn", ("espn", "injuries"))):
        r = conn.execute("SELECT MAX(fetched_at) FROM raw_fetch_log WHERE source = ? AND endpoint = ?", (src, ep)).fetchone()
        ev.feeds[name] = r[0]
    return ev


# ------------------------------------------------------------------ deciding --
def signature(snap: dict) -> str:
    n, m = snap.get("nfl") or {}, snap.get("mfl") or {}
    return json.dumps([n.get("game"), n.get("practice"), m.get("status"), espn_state(snap.get("espn"))])


def actionable_nfl(n: dict | None) -> bool:
    return bool(n) and (n.get("game") in GAME_ACTIONABLE or n.get("practice") in PRACTICE_ACTIONABLE)


def carried(prev: dict | None, cur: dict) -> dict:
    """The snapshot to STORE: a feed that is unpublished/unloaded now (its part is None) keeps its previous part."""
    out = dict(cur)
    if prev is not None:
        for part in ("nfl", "espn"):
            if cur.get(part) is None:
                out[part] = prev.get(part)
    return out


def decide(prev: dict | None, prev_week: int | None, cur: dict, week: int) -> dict | None:
    """-> {'kind', 'changes': [(label, old, new)], 'expected'} or None. prev None = no baseline for this player: nothing.
    kind: change | cleared | active | inactive."""
    if prev is None:
        return None
    changes, rolled = [], prev_week != week
    pn, cn = prev.get("nfl"), cur.get("nfl")
    if cn is not None:   # published
        if not rolled or actionable_nfl(cn):
            for label, key in (("Game", "game"), ("Practice", "practice")):
                old, new = (pn or {}).get(key), cn.get(key)
                if old != new:
                    changes.append((label, old, new))
    pm, cm = (prev.get("mfl") or {}).get("status"), (cur.get("mfl") or {}).get("status")
    if pm != cm:
        changes.append(("MFL", pm, cm))
    pe, ce = espn_state(prev.get("espn")), espn_state(cur.get("espn"))
    if cur.get("espn") is not None and pe != ce and (not rolled or flagged_espn(ce)):
        changes.append(("ESPN", pe, ce))
    if not changes:
        return None
    was = actionable_nfl(pn) or bool(pm) or flagged_espn(pe)
    now_ = actionable_nfl(cn) or bool(cm) or flagged_espn(ce)
    if not (was or now_):
        return None   # e.g. nothing -> Full Participation, or nothing -> ACTIVE: not news
    espn_moved = any(label == "ESPN" for label, _, _ in changes)
    if espn_moved and ce == "INACTIVE":
        kind = "inactive"
    elif espn_moved and ce == "ACTIVE":
        kind = "active"
    else:
        kind = "cleared" if (was and not now_) else "change"
    # "as expected": he was already ruled Out by the NFL report, MFL or ESPN before the inactive list
    expected = kind == "inactive" and ((pn or {}).get("game") == "Out" or pm == "Out" or pe in ("OUT", "INACTIVE"))
    return {"kind": kind, "changes": changes, "expected": expected}


# ----------------------------------------------------------------- wording --
def headline(cur: dict, kind: str, expected: bool = False) -> str:
    n, m = cur.get("nfl") or {}, cur.get("mfl") or {}
    who = f"{cur['name']} ({cur['position']}, {cur['team']})"
    if kind == "inactive":
        return f"INACTIVE{' (as expected)' if expected else ' - NOT EXPECTED'}: {who}"
    if kind == "active":
        return f"ACTIVE: {who}"
    if kind == "cleared":
        word = "CLEARED"
    elif n.get("game"):
        word = n["game"].upper()
    elif n.get("practice") in PRACTICE_ACTIONABLE:
        word = {"DNP": "DID NOT PRACTICE", "LP": "LIMITED"}[n["practice"]]
    elif m.get("status"):
        word = m["status"].upper()
    elif espn_state(cur.get("espn")):
        word = espn_state(cur["espn"])
    else:
        word = "UPDATE"
    return f"{word}: {who}"


def _leagues(cur: dict) -> str:
    return ", ".join(f"{lg} ({SLOT_SHOWN.get(sl, sl)})" if SLOT_SHOWN.get(sl, sl) else lg for lg, sl in cur["leagues"])


def _kickoff_line(cur: dict, now) -> str | None:
    g = cur.get("game")
    if not g:
        return None
    mins = (parse_utc(g["kickoff"]) - now).total_seconds() / 60 if now else None
    left = f" (in {int(mins)} min)" if mins is not None and 0 < mins < 24 * 60 else (" (kicked off)" if mins is not None and mins <= 0 else "")
    return f"Kickoff: {g['when']}{left}"


def render(cur: dict, decision: dict, now=None) -> dict:
    kind, n, m, e = decision["kind"], cur.get("nfl") or {}, cur.get("mfl") or {}, cur.get("espn") or {}
    lines = [f"{label}: {old or 'none'} -> {new or 'none'}" for label, old, new in decision["changes"]]
    k = _kickoff_line(cur, now)
    if k:
        lines.append(k)
    if n.get("injury"):
        lines.append(f"Injury (NFL report): {n['injury']}")
    if m.get("status"):
        lines.append(f"MFL: {m['status']}" + (f", {m['details']}" if m.get("details") else "")
                     + (f", expected back {m['exp_return']}" if m.get("exp_return") else ""))
    if e.get("comment"):
        lines.append(f"ESPN: {e['comment'][:200]}")
    lines.append(f"On: {_leagues(cur)}")
    if kind == "inactive":
        priority, tags = (3 if decision.get("expected") else 5), ("x",)
    elif kind == "active":
        priority, tags = 4, ("white_check_mark",)
    else:
        urgent = kind == "change" and (n.get("game") in URGENT_GAME)
        priority = 4 if urgent else (2 if kind == "cleared" else 3)
        tags = ("rotating_light",) if urgent else (("white_check_mark",) if kind == "cleared" else ("warning",))
    return {"kind": kind, "title": headline(cur, kind, decision.get("expected", False)), "body": "\n".join(lines),
            "priority": priority, "tags": tags}


# ------------------------------------------------------------------- state --
def read_state(conn) -> dict:
    return {r["gsis_id"]: (r["week"], json.loads(r["snapshot_json"])) for r in conn.execute("SELECT * FROM app_alert_state")}


def write_state(conn, ev: Evaluation, keep_prev: set, prev: dict, now) -> None:
    """Replace the state with the current snapshots (players no longer rostered drop out, so re-adding one reseeds
    silently). Players in keep_prev (their push failed) keep their previous row so the next run retries."""
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM app_alert_state")
        for gsis, snap in ev.players.items():
            if gsis in keep_prev and gsis in prev:
                week, old = prev[gsis]
                row = (gsis, ev.season, week, signature(old), json.dumps(old, sort_keys=True))
            else:
                store = carried(prev.get(gsis, (None, None))[1], snap)
                row = (gsis, ev.season, ev.week, signature(store), json.dumps(store, sort_keys=True))
            conn.execute("INSERT INTO app_alert_state (gsis_id, season, week, signature, snapshot_json, updated_at) VALUES (?,?,?,?,?,?)",
                         (*row, now.isoformat()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def plan(conn, ev: Evaluation, now=None) -> tuple[list, dict]:
    """-> ([(gsis, rendered alert)], prev state). Pure: reads state, writes nothing."""
    prev = read_state(conn)
    out = []
    for gsis, cur in ev.players.items():
        p = prev.get(gsis)
        d = decide(p[1] if p else None, p[0] if p else None, cur, ev.week)
        if d:
            out.append((gsis, render(cur, d, now)))
    # Out/Doubtful and unexpected inactives first, then by name, so the most important push arrives first
    out.sort(key=lambda x: (-x[1]["priority"], x[1]["title"]))
    return out, prev


def final_plan(conn, ev: Evaluation, now) -> list:
    """-> [(gsis, game_id, rendered)]: players still UNCERTAIN (Questionable/Doubtful by the NFL report or ESPN) with no
    ACTIVE/INACTIVE from ESPN, whose game kicks off within FINAL_AT and has not started, not yet pushed (app_alert_final)."""
    done = {(r[0], r[1]) for r in conn.execute("SELECT gsis_id, game_id FROM app_alert_final WHERE ok = 1")}
    out = []
    for gsis, s in ev.players.items():
        g = s.get("game")
        if not g or (gsis, g["game_id"]) in done:
            continue
        mins = (parse_utc(g["kickoff"]) - now).total_seconds() / 60
        if not (0 < mins <= gameday.FINAL_AT.total_seconds() / 60):
            continue
        es, nfl_game = espn_state(s.get("espn")), (s.get("nfl") or {}).get("game")
        if es in ("ACTIVE", "INACTIVE"):
            continue   # settled, and announced when ESPN posted it
        if not (es in UNCERTAIN or nfl_game in ("Questionable", "Doubtful")):
            continue
        lines = [f"Kickoff in {int(mins)} min: {g['when']}"]
        if nfl_game:
            lines.append(f"NFL report: {nfl_game}" + (f" ({s['nfl']['injury']})" if s["nfl"].get("injury") else ""))
        if es:
            lines.append(f"ESPN: {es.title()}" + (f" - {s['espn']['comment'][:160]}" if s["espn"].get("comment") else ""))
        if ev.espn_loaded and not ev.posted.get(g["team"]):
            lines.append(f"WARNING: ESPN has posted NO game-day entries for {g['team']} yet, so this may only mean the list is late.")
        elif not ev.espn_loaded:
            lines.append("WARNING: no ESPN data is loaded; this check cannot see active/inactive.")
        lines.append(f"On: {_leagues(s)}")
        out.append((gsis, g["game_id"], {"kind": "final", "title": f"NOT CONFIRMED: {s['name']} ({s['position']}, {s['team']})",
                                         "body": "\n".join(lines), "priority": 4, "tags": ("hourglass",)}))
    out.sort(key=lambda x: x[2]["title"])
    return out


# -------------------------------------------------------------------- run --
def refresh(conn, loaders=("nflverse.injuries", "mfl.injuries", "espn.injuries")) -> list[str]:
    """Re-fetch and load injury feeds. -> failure strings (empty = fine)."""
    from .weekly import run_loader
    fails = []
    for lid in loaders:
        try:
            step = run_loader(conn, lid)
        except Exception as e:
            fails.append(f"{lid}: {type(e).__name__}: {e}")
            continue
        fails += [f"{lid}: {f}" for f in step["failures"]]
    return fails


def _push(conn, now, items, ledger) -> set:
    """Send each (gsis, game_id|None, alert); log it; -> gsis ids whose push failed."""
    failed = set()
    conn.execute("BEGIN")
    for gsis, game_id, a in items:
        ok = notify.send(a["title"], a["body"], a["priority"], a["tags"])
        if not ok:
            failed.add(gsis)
        conn.execute("INSERT INTO app_alert_log (logged_at, gsis_id, kind, title, body, ok, detail) VALUES (?,?,?,?,?,?,?)",
                     (now.isoformat(), gsis, a["kind"], a["title"], a["body"], int(ok), None if ok else "push failed; will retry"))
        if ledger and game_id:
            conn.execute("DELETE FROM app_alert_final WHERE gsis_id = ? AND game_id = ?", (gsis, game_id))
            conn.execute("INSERT INTO app_alert_final (gsis_id, game_id, sent_at, ok) VALUES (?,?,?,?)", (gsis, game_id, now.isoformat(), int(ok)))
    conn.execute("COMMIT")
    return failed


def act(conn, ev: Evaluation, send=False, seed=False, now=None, verbose=True) -> int:
    """Decide and (with send) push for one evaluation. -> rc."""
    now = now or utcnow()
    prev = read_state(conn)
    if seed:
        write_state(conn, ev, set(), prev, now)
        print(f"SEEDED the baseline for {len(ev.players)} players. Nothing was sent.")
        return 0
    if send and not prev:
        print("!!! no baseline yet: run `python -m fdb alerts --seed` first (otherwise every status would push at once). Nothing sent.")
        return 1
    alerts, prev = plan(conn, ev, now)
    finals = final_plan(conn, ev, now) if prev else []
    if not prev:
        print("no baseline recorded yet (dry run): every player would be treated as new. Run with --seed to record one.")
        return 0
    if not alerts and verbose:
        print("no status changes since the last recorded state")
    for gsis, a in alerts:
        print(f"\n[{a['kind']}] priority {a['priority']}: {a['title']}\n{a['body']}")
    for gsis, gid, a in finals:
        print(f"\n[final] priority {a['priority']}: {a['title']}\n{a['body']}")
    if not send:
        print(f"\n(dry run: {len(alerts)} alert(s) and {len(finals)} final check(s) would be sent; nothing sent, nothing written. Pass --send to push them.)")
        return 0
    failed = _push(conn, now, [(g, None, a) for g, a in alerts], False)
    failed_final = _push(conn, now, finals, True)
    write_state(conn, ev, failed, prev, now)
    nsent = len(alerts) - len(failed) + len(finals) - len(failed_final)
    nall = len(alerts) + len(finals)
    if nall or verbose:
        print(f"\nsent {nsent} of {nall} push(es)" + (f"; {len(failed) + len(failed_final)} FAILED and will retry next run" if failed or failed_final else ""))
    return 1 if failed or failed_final else 0


def run(conn, do_refresh=False, send=False, seed=False, now=None) -> int:
    now = now or utcnow()
    rc = 0
    if do_refresh:
        fails = refresh(conn)
        for f in fails:
            print(f"!!! REFRESH FAILED, using the data already loaded: {f}")
        rc = 1 if fails else 0
    ev = evaluate(conn, now)
    if ev is None:
        print("no live report week (offseason or no schedule loaded); nothing to do")
        return rc
    n_act = sum(1 for s in ev.players.values() if actionable_nfl(s.get("nfl")) or (s.get("mfl") or {}).get("status")
                or flagged_espn(espn_state(s.get("espn"))))
    print(f"season {ev.season} {ev.season_type} week {ev.week}: {len(ev.players)} rostered NFL players tracked "
          f"({n_act} carrying a status); NFL report for this week is "
          f"{'PUBLISHED' if ev.nfl_published else 'NOT PUBLISHED YET (NFL statuses held, not compared)'}")
    print(f"feeds fetched: NFL {ev.feeds.get('nfl') or 'never'}, MFL {ev.feeds.get('mfl') or 'never'}, ESPN {ev.feeds.get('espn') or 'never'}"
          + ("" if ev.espn_loaded else "  (ESPN: no rows for this season/type)"))
    if not ev.players:
        print("no rostered players resolved to an NFL id; is the roster snapshot loaded?")
        return 1
    return act(conn, ev, send=send, seed=seed, now=now) or rc


# ------------------------------------------------------------------- watch --
@contextlib.contextmanager
def _lock(stale_after=timedelta(hours=1)):
    """One watcher at a time: two would race on app_alert_state and push twice. The file is touched every poll, so a
    crashed watcher's lock goes stale and is taken over."""
    path = config.DB_PATH.parent / "alerts_watch.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - path.stat().st_mtime
        if age < stale_after.total_seconds():
            raise SystemExit(f"another alerts watcher holds {path} (touched {int(age)} s ago); not starting a second one")
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def watch(conn, send=False, poll_s=POLL_SECONDS, horizon_h=14, now_fn=utcnow, sleep=time.sleep, max_polls=None) -> int:
    """Poll ESPN only inside kickoff windows (LEAD before each game until kickoff). Outside one it sleeps until the next
    opens, and exits if none opens within `horizon_h` hours (so a daily Task Scheduler start is cheap and idempotent).
    Slow feeds (NFL report file, MFL) refresh every FULL_REFRESH_EVERY polls. -> rc (1 if any poll failed)."""
    if send and not read_state(conn):
        print("!!! no baseline yet: run `python -m fdb alerts --seed` first. Nothing will be sent; not watching.")
        return 1
    rc, polls, espn_fail_run, warned = 0, 0, 0, False
    with _lock() as lock:
        while True:
            now = now_fn()
            os.utime(lock)
            season = schedule.current_season(conn, now)
            wk = report_week(conn, season, now) if season else None
            gs = gameday.games(conn, season, *wk) if wk else []
            if not gameday.open_games(gs, now):
                nxt = gameday.next_open(gs, now)
                if nxt is None or nxt - now > timedelta(hours=horizon_h):
                    print(f"{now.isoformat()}: no kickoff window opens within {horizon_h} h; exiting")
                    return rc
                wait = min((nxt - now).total_seconds(), 300)
                if wait > 60 and not warned:
                    print(f"{now.isoformat()}: next window opens {nxt.isoformat()}; sleeping")
                    warned = True
                sleep(max(wait, 1))
                continue
            warned = False
            loaders = ("espn.injuries",) + (("nflverse.injuries", "mfl.injuries") if polls % FULL_REFRESH_EVERY == 0 else ())
            fails = refresh(conn, loaders)
            espn_fail_run = espn_fail_run + 1 if any(f.startswith("espn.injuries") for f in fails) else 0
            for f in fails:
                print(f"{now.isoformat()}: !!! REFRESH FAILED, using what is loaded: {f}")
            if espn_fail_run == FEED_FAILS_BEFORE_PUSH and send:
                notify.send("ALERTS: ESPN feed failing", f"The ESPN injuries feed failed {espn_fail_run} polls in a row inside a kickoff "
                            "window. Active/inactive alerts are NOT arriving. Check data/logs and the network.", 4, ("warning",))
            ev = evaluate(conn, now)
            if ev:
                rc = act(conn, ev, send=send, now=now, verbose=False) or (1 if fails else 0) or rc
            polls += 1
            if max_polls and polls >= max_polls:
                return rc
            sleep(poll_s)


def test_push() -> int:
    ok = notify.send("football_db_v2 test", "If you can read this on your phone, push works. No loaders were run.", 3, ("white_check_mark",))
    print("test push sent" if ok else "test push NOT sent (see above)")
    return 0 if ok else 1
