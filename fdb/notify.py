"""Phone push through ntfy (Phase 12), for the player-status alerts in fdb/alerts.py.

Settings (env or .env, never logged): NTFY_TOPIC (required; on the public server the topic NAME is the only
secret, so make it long and random), NTFY_SERVER (default https://ntfy.sh), NTFY_TOKEN (optional bearer token for
a protected topic or a self-hosted server).

Same three behaviours as fdb/alert.py, deliberately:
  * topic unset  -> says so LOUDLY and returns False; it must not read like a clean run
  * server not https -> refuses to post (a typo must not send over plain http)
  * failure -> prints the exception only, never the topic or token
A failed push never raises: the caller keeps the alert pending and retries on the next run."""
import json

from . import config, http

MAX_BODY = 3500   # ntfy caps a message at 4096 bytes; leave room for multi-byte characters


def _settings() -> tuple[str, str, str]:
    return (config.env("NTFY_TOPIC"), config.env("NTFY_SERVER", "https://ntfy.sh").rstrip("/"), config.env("NTFY_TOKEN"))


def configured() -> bool:
    return bool(_settings()[0])


def send(title: str, message: str, priority: int = 3, tags: tuple[str, ...] = ()) -> bool:
    topic, server, token = _settings()
    if not topic:
        print("!!! PUSH NOT SENT: NTFY_TOPIC is unset (put it in .env). Nothing was delivered to your phone.")
        return False
    if not server.startswith("https://"):
        print("!!! PUSH NOT SENT: NTFY_SERVER is not an https URL. Refusing to post.")
        return False
    body = {"topic": topic, "title": title[:250], "message": message[:MAX_BODY],
            "priority": max(1, min(5, int(priority)))}
    if tags:
        body["tags"] = list(tags)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status, _, _ = http.request(server, data=json.dumps(body).encode("utf-8"), headers=headers, timeout=30)
        return 200 <= status < 300
    except Exception as e:  # never echo the topic or token
        print(f"!!! PUSH FAILED: {type(e).__name__}: {e}".replace(topic, "<topic>").replace(token or "\0", "<token>"))
        return False
