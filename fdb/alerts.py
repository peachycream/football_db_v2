"""Player-status alerts (Phase 12, part A): which of MY rostered players changed status, pushed to my phone.

Reads only mart_roster_ownership (is_mine, every league on every platform loaded), mart_injury_nfl and
mart_injury_mfl, joined on gsis_id. Keeps what it last told me in app_alert_state, so a status is announced once.

Decisions that are deliberate, each from a way this could mislead or flood:
  * The two feeds are never merged into one "status". An alert shows the NFL report's game designation and
    practice participation and MFL's own status as separate lines, because they are different claims.
  * A report week with NO rows in the NFL file means "not published yet" (the file holds weeks 1-4 until
    Wednesday's week-5 report arrives), never "everyone is healthy". The NFL part of the state is then carried
    forward untouched and nothing is announced from it.
  * The first run is a silent baseline (`--seed`); `--send` refuses to run before one exists, so turning this on
    cannot push a few hundred "changes".
  * When the report week rolls over, last week's designations are not announced as "cleared"; only a new
    actionable designation is. (MFL's status is not week-bound and is always compared.)
  * A push that fails keeps that player's PREVIOUS state, so the next run tries again. A failure is logged.
  * Nothing here sends unless `--send` is given. The default is a dry run with no network and no writes.

What it cannot do yet (part B, not built): the inactive list, kickoff-relative polling, lineup awareness, news.
The nflverse file carries no per-row time, so this layer knows what a status IS, never when it changed."""
import json
from dataclasses import dataclass, field

from . import notify, schedule
from .timeutil import utcnow

GAME_ACTIONABLE = ("Out", "Doubtful", "Questionable")
PRACTICE_SHORT = (("Did Not", "DNP"), ("Limited", "LP"), ("Full", "FP"))
PRACTICE_ACTIONABLE = ("DNP", "LP")
SLOT_SHOWN = {"roster": "", "starter": "starter", "bench": "bench", "taxi": "taxi", "ir": "IR"}
URGENT_GAME = ("Out", "Doubtful")


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
    players: dict = field(default_factory=dict)   # gsis_id -> snapshot dict (see snapshot())
    feeds: dict = field(default_factory=dict)     # name -> raw fetched_at, for the staleness line


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
    ev = Evaluation(season, st, week, published)
    for gsis, info in rostered(conn, season).items():
        n, m = nfl.get(gsis), mfl.get(gsis)
        ev.players[gsis] = {
            **info,
            "nfl": ({"game": (n["game_status"] if n else None) or None,
                     "practice": practice_short(n["practice_status"]) if n else None,
                     "injury": ((n["game_injury"] or n["practice_injury"]) if n else None) or None} if published else None),
            "mfl": {"status": m["mfl_status"], "details": m["mfl_details"] or None, "exp_return": m["mfl_exp_return"] or None} if m else None,
        }
    for name, (src, ep) in (("nfl", ("nflverse", "injuries")), ("mfl", ("mfl", "injuries"))):
        r = conn.execute("SELECT MAX(fetched_at) FROM raw_fetch_log WHERE source = ? AND endpoint = ?", (src, ep)).fetchone()
        ev.feeds[name] = r[0]
    return ev


# ------------------------------------------------------------------ deciding --
def signature(snap: dict) -> str:
    n, m = snap.get("nfl") or {}, snap.get("mfl") or {}
    return json.dumps([n.get("game"), n.get("practice"), m.get("status")])


def actionable_nfl(n: dict | None) -> bool:
    return bool(n) and (n.get("game") in GAME_ACTIONABLE or n.get("practice") in PRACTICE_ACTIONABLE)


def carried(prev: dict | None, cur: dict) -> dict:
    """The snapshot to STORE: when the NFL report is unpublished (cur nfl is None) keep the previous NFL part."""
    if cur.get("nfl") is None and prev is not None:
        return {**cur, "nfl": prev.get("nfl")}
    return cur


def decide(prev: dict | None, prev_week: int | None, cur: dict, week: int) -> dict | None:
    """-> {'kind', 'changes': [(label, old, new)]} or None. prev None = no baseline for this player: nothing."""
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
    if not changes:
        return None
    was = actionable_nfl(pn) or bool(pm)
    now_ = actionable_nfl(cn) or bool(cm)
    if not (was or now_):
        return None   # e.g. nothing -> Full Participation: not news
    return {"kind": "cleared" if (was and not now_) else "change", "changes": changes}


# ----------------------------------------------------------------- wording --
def headline(cur: dict, kind: str) -> str:
    n, m = cur.get("nfl") or {}, cur.get("mfl") or {}
    if kind == "cleared":
        word = "CLEARED"
    elif n.get("game"):
        word = n["game"].upper()
    elif n.get("practice") in PRACTICE_ACTIONABLE:
        word = {"DNP": "DID NOT PRACTICE", "LP": "LIMITED"}[n["practice"]]
    elif m.get("status"):
        word = m["status"].upper()
    else:
        word = "UPDATE"
    return f"{word}: {cur['name']} ({cur['position']}, {cur['team']})"


def render(cur: dict, decision: dict) -> dict:
    kind, n, m = decision["kind"], cur.get("nfl") or {}, cur.get("mfl") or {}
    lines = [f"{label}: {old or 'none'} -> {new or 'none'}" for label, old, new in decision["changes"]]
    if n.get("injury"):
        lines.append(f"Injury (NFL report): {n['injury']}")
    if m.get("status"):
        lines.append(f"MFL: {m['status']}" + (f", {m['details']}" if m.get("details") else "")
                     + (f", expected back {m['exp_return']}" if m.get("exp_return") else ""))
    on = ", ".join(f"{lg} ({SLOT_SHOWN.get(sl, sl)})" if SLOT_SHOWN.get(sl, sl) else lg for lg, sl in cur["leagues"])
    lines.append(f"On: {on}")
    urgent = kind == "change" and (n.get("game") in URGENT_GAME)
    return {"kind": kind, "title": headline(cur, kind), "body": "\n".join(lines),
            "priority": 4 if urgent else (2 if kind == "cleared" else 3),
            "tags": ("rotating_light",) if urgent else (("white_check_mark",) if kind == "cleared" else ("warning",))}


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


def plan(conn, ev: Evaluation) -> tuple[list, dict]:
    """-> ([(gsis, rendered alert)], prev state). Pure: reads state, writes nothing."""
    prev = read_state(conn)
    out = []
    for gsis, cur in ev.players.items():
        p = prev.get(gsis)
        d = decide(p[1] if p else None, p[0] if p else None, cur, ev.week)
        if d:
            out.append((gsis, render(cur, d)))
    # Out/Doubtful first, then by name, so the most important push arrives first
    out.sort(key=lambda x: (-x[1]["priority"], x[1]["title"]))
    return out, prev


# -------------------------------------------------------------------- run --
def refresh(conn) -> list[str]:
    """Re-fetch and load both injury feeds. -> failure strings (empty = fine)."""
    from .weekly import run_loader
    fails = []
    for lid in ("nflverse.injuries", "mfl.injuries"):
        try:
            step = run_loader(conn, lid)
        except Exception as e:
            fails.append(f"{lid}: {type(e).__name__}: {e}")
            continue
        fails += [f"{lid}: {f}" for f in step["failures"]]
    return fails


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
    n_act = sum(1 for s in ev.players.values() if actionable_nfl(s.get("nfl")) or (s.get("mfl") or {}).get("status"))
    print(f"season {ev.season} {ev.season_type} week {ev.week}: {len(ev.players)} rostered NFL players tracked "
          f"({n_act} carrying a status); NFL report for this week is "
          f"{'PUBLISHED' if ev.nfl_published else 'NOT PUBLISHED YET (NFL statuses held, not compared)'}")
    print(f"feeds fetched: NFL {ev.feeds.get('nfl') or 'never'}, MFL {ev.feeds.get('mfl') or 'never'}")
    if not ev.players:
        print("no rostered players resolved to an NFL id; is the roster snapshot loaded?")
        return 1

    prev = read_state(conn)
    if seed:
        write_state(conn, ev, set(), prev, now)
        print(f"SEEDED the baseline for {len(ev.players)} players. Nothing was sent.")
        return rc
    if send and not prev:
        print("!!! no baseline yet: run `python -m fdb alerts --seed` first (otherwise every status would push at once). Nothing sent.")
        return 1
    alerts, prev = plan(conn, ev)
    if not prev:
        print("no baseline recorded yet (dry run): every player would be treated as new. Run with --seed to record one.")
        return rc
    if not alerts:
        print("no status changes since the last recorded state")
    for gsis, a in alerts:
        print(f"\n[{a['kind']}] priority {a['priority']}: {a['title']}\n{a['body']}")
    if not send:
        print(f"\n(dry run: {len(alerts)} alert(s) would be sent; nothing sent, nothing written. Pass --send to push them.)")
        return rc

    failed = set()
    conn.execute("BEGIN")
    for gsis, a in alerts:
        ok = notify.send(a["title"], a["body"], a["priority"], a["tags"])
        if not ok:
            failed.add(gsis)
        conn.execute("INSERT INTO app_alert_log (logged_at, gsis_id, kind, title, body, ok, detail) VALUES (?,?,?,?,?,?,?)",
                     (now.isoformat(), gsis, a["kind"], a["title"], a["body"], int(ok), None if ok else "push failed; will retry"))
    conn.execute("COMMIT")
    write_state(conn, ev, failed, prev, now)
    print(f"\nsent {len(alerts) - len(failed)} of {len(alerts)} alert(s)" + (f"; {len(failed)} FAILED and will retry next run" if failed else ""))
    return 1 if failed else rc


def test_push() -> int:
    ok = notify.send("football_db_v2 test", "If you can read this on your phone, push works. No loaders were run.", 3, ("white_check_mark",))
    print("test push sent" if ok else "test push NOT sent (see above)")
    return 0 if ok else 1
