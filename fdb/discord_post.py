"""Post the Matchup of the Week to Discord. MANUAL and for league 30590 ONLY (Turon's decision). Nothing here runs by itself,
and nothing is sent unless `fdb post --send` is run (and confirmed) by a person.

    fdb post --mode recap|preview             DRY RUN: renders everything, saves the images, PRINTS the text, sends nothing
    fdb post --mode recap|preview --send      asks "Post to Discord?" and, on yes, posts the messages below

A post is THREE Discord messages, because Discord shows an attachment inside roughly a 550 x 400 box: a tall image shows tiny,
a landscape one shows large, and message text is shown at full size.
    1. the cover panel (landscape image) under the caption "<league> - Week N recap|preview - Matchup of the Week"
    2. the position-board panel (landscape image)
    3. "The breakdown": the written commentary (fdb/matchup_commentary.py), as the message text

What makes it safe to run by hand:
  * the week and the game come from fdb/matchup_weeks.py and the picker, never from "the current week" (v1's bug);
  * at most one post per league, season, week and mode (app_post_log, claimed BEFORE any request, exported across rebuilds),
    tracked PART BY PART: a failure part-way is resumed by the next run from the first undelivered message, so a message is
    never posted twice by a retry. `--repost` is the one deliberate override and a human has to type it;
  * the webhook (MOTW_DISCORD_WEBHOOK_30590 in .env, never in git or logs) must be a real Discord webhook URL; a placeholder,
    a non-https URL or another host is refused; the URL and its token are never printed, not even in an error;
  * `allowed_mentions` is empty on every message: a post can never ping anyone;
  * it refuses when the weekly job failed or is stale, when the target week is not ready, and (preview) when no pre-kickoff
    projection exists, each with its reason; flags exist for the last two so the person decides, not the code.
Every network call goes through fdb/http.py (the only network path); `fdb rebuild` disables it."""
import hashlib
import json
import re
import sys
import time
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone

from . import card_render, config, http, matchup_card as mc, matchup_commentary, matchup_weeks
from .timeutil import utcnow

LEAGUES = ("30590",)                      # Turon: 30590 only
ENV_PREFIX = "MOTW_DISCORD_WEBHOOK_"      # + the league id
WEBHOOK_RE = re.compile(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+$")
STATUS_MAX_AGE = timedelta(days=9)        # the weekly job runs weekly; older than this and the data may be stale
MAX_429_RETRIES = 3
MAX_RETRY_WAIT = 30.0
MESSAGE_LIMIT = 2000                      # Discord's cap on message text
PAUSE_BETWEEN_PARTS = 0.6                 # seconds, so the three messages land in order and stay clear of rate limits


class PostError(RuntimeError):
    pass


def webhook_for(league: str) -> str:
    return config.env(ENV_PREFIX + league)


def valid_webhook(url: str) -> bool:
    return bool(url) and bool(WEBHOOK_RE.match(url))


def redact(text: str, url: str) -> str:
    """Remove the webhook (and its token on its own) from anything about to be printed or stored."""
    if not url:
        return text
    token = url.rstrip("/").rsplit("/", 1)[-1]
    out = text.replace(url, "<webhook>")
    return out.replace(token, "<token>") if len(token) >= 8 else out


# ------------------------------------------------------------------ the request --
def multipart(payload: dict, filename: str, png: bytes):
    """-> (body, content type). One JSON payload part and one file part, as Discord's webhook API expects."""
    boundary = "fdb" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'.encode(),
        json.dumps(payload).encode("utf-8"), b"\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode(),
        png, b"\r\n", f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send(url: str, content: str, png: bytes = None, filename: str = None):
    """POST ONE message: text, or text plus one image. -> (ok, message_id or None, detail). Never raises, never returns the
    URL. A 429 is retried after the wait Discord names; any other HTTP error or a dead connection is a definite failure."""
    payload = {"content": content[:MESSAGE_LIMIT], "allowed_mentions": {"parse": []}}
    if png is not None:
        payload["attachments"] = [{"id": 0, "filename": filename}]
        body, ctype = multipart(payload, filename, png)
    else:
        body, ctype = json.dumps(payload).encode("utf-8"), "application/json"
    target = url + ("&" if "?" in url else "?") + "wait=true"   # ask Discord for the message, so we keep its id
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            status, _, resp = http.request(target, data=body, headers={"Content-Type": ctype}, timeout=60)
            try:
                mid = str(json.loads(resp).get("id") or "") or None
            except ValueError:
                mid = None
            return 200 <= status < 300, mid, f"HTTP {status}"
        except urllib.error.HTTPError as e:
            text = ""
            try:
                text = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code == 429 and attempt < MAX_429_RETRIES:
                try:
                    wait = float(json.loads(text).get("retry_after", 1.0))
                except (ValueError, AttributeError):
                    wait = 1.0
                time.sleep(min(max(wait, 0.1), MAX_RETRY_WAIT))
                continue
            return False, None, redact(f"HTTP {e.code} {text[:200]}".strip(), url)
        except Exception as e:   # no connection, timeout, network disabled
            return False, None, redact(f"{type(e).__name__}: {e}", url)
    return False, None, "rate limited and out of retries"


# ----------------------------------------------------------------------- content --
def caption(card: dict, mode: str) -> str:
    word = {"recap": "recap", "live": "so far"}.get(mode, "preview")
    return f"**{card['league_name']} - Week {card['week']} {word} · Matchup of the Week**"


def build_parts(card: dict, mode: str, panels: dict, commentary: str, stem: str) -> list:
    """The messages, in order: [{"name", "content", "png" or None, "filename"}]. The breakdown is skipped when there is none."""
    parts = [{"name": "cover", "content": caption(card, mode), "png": panels["cover"], "filename": f"{stem}_cover.png"},
             {"name": "board", "content": "**Position board**" + (" (points so far)" if card.get("live") else " (projected)" if card["state"] != "FINAL" else ""),
              "png": panels["board"], "filename": f"{stem}_board.png"}]
    if commentary:
        head = "**The breakdown**\n\n"
        parts.append({"name": "breakdown", "content": head + commentary[:MESSAGE_LIMIT - len(head)], "png": None, "filename": None})
    return parts


def content_hash(parts: list) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p["content"].encode("utf-8"))
        h.update(p["png"] or b"")
    return h.hexdigest()


# --------------------------------------------------------------------- the log --
def log_row(conn, league, season, week, mode):
    return conn.execute("SELECT * FROM app_post_log WHERE league_id = ? AND season = ? AND week = ? AND mode = ?",
                        (league, season, week, mode)).fetchone()


def now_text() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def is_complete(row) -> bool:
    """A posted row is complete; a row written before the parts migration (parts_total NULL) was one message."""
    return row["status"] == "posted" and (row["parts_total"] is None or row["parts_posted"] >= row["parts_total"])


def claim(conn, key, sha, home, away, repost: bool, total: int = 1, detail: str = ""):
    """Record that a send is about to happen. -> (ok, reason, start_part). Refuses a week that is posted (or whose last
    attempt never finished) unless `repost`; a 'failed' row RESUMES from its first undelivered part with no flag."""
    league, season, week, mode = key
    row = log_row(conn, *key)
    start = 0
    if row is not None and not repost:
        if is_complete(row):
            return False, f"already posted at {row['posted_at']} (message {row['message_id'] or 'unknown'}); --repost to post it again", 0
        if row["status"] == "sending":
            got = row["parts_posted"] or 0
            return False, (f"a previous attempt (claimed {row['claimed_at']}) never finished ({got} message(s) confirmed), so the next one MAY have "
                           "been delivered. Look at the Discord channel; if it is not there, run again with --repost (which posts everything again)"), 0
        start = min(row["parts_posted"] or 0, total)          # failed: resume
    conn.execute("BEGIN")
    try:
        if row is not None and not repost and start > 0:
            conn.execute("""UPDATE app_post_log SET status = 'sending', claimed_at = ?, png_sha256 = ?, parts_total = ?, detail = ?
                            WHERE league_id = ? AND season = ? AND week = ? AND mode = ?""",
                         (now_text(), sha, total, f"resumed at part {start + 1}", *key))
        else:
            conn.execute("DELETE FROM app_post_log WHERE league_id = ? AND season = ? AND week = ? AND mode = ?", key)
            conn.execute("""INSERT INTO app_post_log (league_id, season, week, mode, status, claimed_at, png_sha256, home_id, away_id,
                                                      detail, parts_total, parts_posted)
                            VALUES (?, ?, ?, ?, 'sending', ?, ?, ?, ?, ?, ?, 0)""",
                         (*key, now_text(), sha, home, away, detail or None, total))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return True, "", start


def record_part(conn, key, index: int, message_id):
    """One message was delivered: remember it IMMEDIATELY, so a crash on the next one loses nothing."""
    row = log_row(conn, *key)
    ids = [x for x in (row["message_ids"] or "").split(",") if x] + [message_id or "?"]
    conn.execute("""UPDATE app_post_log SET parts_posted = ?, message_ids = ? WHERE league_id = ? AND season = ? AND week = ? AND mode = ?""",
                 (index + 1, ",".join(ids), *key))
    conn.commit()


def finish(conn, key, ok: bool, detail: str):
    row = log_row(conn, *key)
    first = (row["message_ids"] or "").split(",")[0] or None
    conn.execute("""UPDATE app_post_log SET status = ?, posted_at = ?, message_id = ?, detail = ?
                    WHERE league_id = ? AND season = ? AND week = ? AND mode = ?""",
                 ("posted" if ok else "failed", now_text() if ok else None, first, detail, *key))
    conn.commit()


# ----------------------------------------------------------------------- gates --
def weekly_status(now=None):
    """(ok, reason): the last `fdb weekly` finished OK and recently enough for the data to be current."""
    try:
        st = json.loads(config.STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "PIPELINE_STATUS.json is missing or unreadable, so the last weekly run is unknown"
    if st.get("state") != "ok":
        return False, f"the last weekly run is '{st.get('state')}', not ok"
    try:
        done = datetime.fromisoformat(str(st["finished_at"]).replace("Z", "+00:00"))
        if done.tzinfo is None:
            done = done.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return False, "the last weekly run has no finish time"
    age = (now or utcnow()) - done
    if age > STATUS_MAX_AGE:
        return False, f"the last weekly run finished {age.days} days ago; the data may be out of date"
    return True, ""


# ------------------------------------------------------------------------- run --
def run(conn, mode: str, league: str = "30590", send_it: bool = False, yes: bool = False, repost: bool = False,
        ignore_weekly_status: bool = False, allow_no_projection: bool = False, ask=input,
        game: str | None = None) -> int:
    """The `fdb post` command. -> exit code (0 = done or a clean dry run, 1 = refused or failed). Prints what it did."""
    say = print
    if league not in LEAGUES:
        say(f"post: posting is enabled for league {', '.join(LEAGUES)} only, not {league}")
        return 1
    target = {"recap": matchup_weeks.recap_target, "live": matchup_weeks.live_target}.get(mode, matchup_weeks.preview_target)(conn, league)
    if not target["ready"]:
        say(f"post: {mode} is not ready: {target['reason']}")
        return 1
    if mode == "preview" and not target["projected"] and not allow_no_projection:
        say(f"post: the preview for week {target['week']} is not fully projected: {target['reason']}. "
            "Re-run with --allow-no-projection to post it anyway")
        return 1
    ok, why = weekly_status()
    if not ok and not ignore_weekly_status:
        say(f"post: {why}. Re-run with --ignore-weekly-status if you have checked the data yourself")
        return 1
    f = target["featured"]
    if game:   # a person chose the game: it must be one of this week's games in this league; the picker's top game is not used
        from . import matchup_choices
        pair = matchup_choices.parse_pair(game)
        rows = conn.execute("SELECT home_id, away_id FROM mart_matchup_card WHERE league_id = ? AND season = ? AND week = ?",
                            (league, target["season"], target["week"])).fetchall()
        hit = next((r for r in rows if pair and {r["home_id"], r["away_id"]} == set(pair)), None)
        if hit is None:
            say(f"post: --game {game!r} is not a game in week {target['week']} (use two franchise ids like 0024:0023; see `fdb choices`)")
            return 1
        f = {"home_id": hit["home_id"], "away_id": hit["away_id"]}
    card = mc.card(conn, league, target["season"], target["week"], f["home_id"], f["away_id"])
    if card is None:
        say("post: the featured game is no longer in the mart")
        return 1
    if game:    # chosen by hand: it is the Matchup of the Week, and the picker's reasoning is not part of the post
        card["featured"], card["pick"] = True, None
        say(f"post: game chosen by hand ({game}); the picker's own top game was {target['featured']['home_id']}:{target['featured']['away_id']}"
            if target.get("featured") else f"post: game chosen by hand ({game})")
    try:
        panels = card_render.render_panels(card)
    except card_render.RenderError as e:
        say(f"post: could not render the card: {e}")
        return 1
    commentary = matchup_commentary.to_markdown(matchup_commentary.paragraphs(conn, card), limit=MESSAGE_LIMIT - 30)
    folder = card_render.CARDS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    parts = build_parts(card, mode, panels, commentary, card_render.filename(card)[:-4])
    for p in parts:
        if p["png"]:
            (folder / p["filename"]).write_bytes(p["png"])
    sha = content_hash(parts)
    key = (league, target["season"], target["week"], mode)
    row = log_row(conn, *key)
    url = webhook_for(league)
    say(f"post: {mode} for {card['league_name']} {target['season']} week {target['week']}: "
        f"{card['away']['name']} at {card['home']['name']} ({card['state']}, ranked on {(card['pick'] or {}).get('basis')})")
    say(f"post: {len(parts)} messages: " + "; ".join(
        f"{p['name']} ({len(p['png']) // 1024} KB image)" if p["png"] else f"{p['name']} ({len(p['content'])} characters of text)" for p in parts))
    for p in parts:
        if p["png"]:
            say(f"post: image {folder / p['filename']}")
    say(f"post: content sha256 {sha[:12]}; log: "
        + ("not posted yet" if row is None else row["status"] + (f" at {row['posted_at']}" if row["posted_at"] else "")
           + (f" ({row['parts_posted']} of {row['parts_total']} parts)" if row["parts_total"] else ""))
        + f"; webhook: {'set' if valid_webhook(url) else ('NOT A DISCORD WEBHOOK URL' if url else 'not set')}")
    if commentary:
        say("post: the breakdown that would be posted:")
        for line in parts[-1]["content"].splitlines():
            say("    " + line)
    if not send_it:
        say("post: DRY RUN. Nothing was sent. Re-run with --send to post it")
        return 0
    if not url:
        say(f"post: NOT SENT: {ENV_PREFIX}{league} is not set in .env, so there is nowhere to post")
        return 1
    if not valid_webhook(url):
        say(f"post: NOT SENT: {ENV_PREFIX}{league} is not a Discord webhook URL (https://discord.com/api/webhooks/<id>/<token>)")
        return 1
    if not yes:
        if not sys.stdin or not sys.stdin.isatty():
            say("post: NOT SENT: --send asks for confirmation and there is no terminal here; pass --yes to confirm in advance")
            return 1
        try:
            answer = ask(f"Post this {mode} to Discord now ({len(parts)} messages)? Type yes: ")
        except (EOFError, OSError):   # a "terminal" that cannot be read is no terminal
            say("post: NOT SENT: --send asks for confirmation and the terminal cannot be read; pass --yes to confirm in advance")
            return 1
        if answer.strip().lower() != "yes":
            say("post: cancelled; nothing was sent")
            return 1
    ok, why, start = claim(conn, key, sha, f["home_id"], f["away_id"], repost, total=len(parts),
                           detail="reposted" if (repost and row is not None) else "")
    if not ok:
        say(f"post: NOT SENT: {why}")
        return 1
    if start:
        say(f"post: resuming: {start} of {len(parts)} messages were already delivered")
    for i in range(start, len(parts)):
        p = parts[i]
        if i > start:
            time.sleep(PAUSE_BETWEEN_PARTS)
        sent, mid, detail = send(url, p["content"], p["png"], p["filename"])
        if not sent:
            finish(conn, key, False, f"part {i + 1} of {len(parts)} ({p['name']}): {detail}")
            say(f"post: FAILED on message {i + 1} of {len(parts)} ({p['name']}): {detail}. {i} delivered; run again to resume from here")
            return 1
        record_part(conn, key, i, mid)
        say(f"post: delivered {i + 1}/{len(parts)} ({p['name']}), Discord message id {mid or 'unknown'}")
    finish(conn, key, True, f"HTTP 200 x{len(parts)}")
    say(f"post: POSTED all {len(parts)} messages")
    return 0
