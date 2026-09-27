"""Ops alerting to a PRIVATE Discord channel via OPS_DISCORD_WEBHOOK.

Three behaviours, all deliberate (carried over from v1):
  * unset  -> says so LOUDLY; it must not read like a clean run
  * not a URL -> refuses to post, so a leftover placeholder can't pass as working
  * failure -> prints the exception only, never the URL (the token is the secret)
A failed alert never fails the run."""
import json

from . import config, http


def _webhook() -> str:
    return config.env("OPS_DISCORD_WEBHOOK")


def send(text: str) -> bool:
    url = _webhook()
    if not url:
        print("!!! ALERT NOT SENT: OPS_DISCORD_WEBHOOK is unset. PIPELINE_STATUS.json has the result, but NOBODY IS TOLD.")
        return False
    if not url.startswith("https://"):
        print("!!! ALERT NOT SENT: OPS_DISCORD_WEBHOOK is not an https URL (placeholder?). Refusing to post.")
        return False
    try:
        http.post_json(url, json.dumps({"content": text[:1900]}).encode())
        return True
    except Exception as e:  # never echo the URL
        print(f"!!! ALERT FAILED: {type(e).__name__}: {e}".replace(url, "<webhook>"))
        return False
