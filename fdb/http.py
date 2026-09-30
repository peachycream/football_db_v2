"""The only way code in this package touches the network.

`fdb rebuild` sets NETWORK_ENABLED = False, so a rebuild that tries to fetch
fails loudly instead of quietly depending on the network (REBUILD_DESIGN §2.2).

TRANSPORT RETRIES (Phase 8): the scheduled job runs unattended on a home connection
that drops for minutes at a time (2026-09-28 and 09-30: DNS "getaddrinfo failed",
"connection forcibly closed"). A network-level failure is retried with backoff
(15/30/60/120 s, ~4 min in all) before it is raised. An HTTP error RESPONSE is never
retried here - it is the source answering, and callers own that (PFF 429, FTN 404)."""
import http.client
import socket
import time
import urllib.error
import urllib.request

NETWORK_ENABLED = True
CALLS = 0
RETRY_WAITS = (15, 30, 60, 120)


def _transient(e: BaseException) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return False
    return isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout,
                          http.client.RemoteDisconnected, http.client.IncompleteRead))


def _open(req, timeout: int):
    """urlopen with transport retries; returns (status, headers, body)."""
    global CALLS
    for i in range(len(RETRY_WAITS) + 1):
        CALLS += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.headers, resp.read()
        except Exception as e:
            if not _transient(e) or i == len(RETRY_WAITS):
                raise
            wait = RETRY_WAITS[i]
            print(f"[http] {type(e).__name__} on {req.full_url.split('?')[0]}; retry {i + 1}/{len(RETRY_WAITS)} in {wait}s")
            time.sleep(wait)


class NetworkDisabled(RuntimeError):
    pass


def get(url: str, headers: dict | None = None, timeout: int = 120) -> bytes:
    if not NETWORK_ENABLED:
        raise NetworkDisabled(f"network call attempted while disabled: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "football_db_v2", **(headers or {})})
    return _open(req, timeout)[2]


def request(url: str, data: bytes | None = None, headers: dict | None = None,
            timeout: int = 60) -> tuple[int, object, bytes]:
    """-> (status, response headers, body). Raises urllib.error.HTTPError on 4xx/5xx.
    For callers that need response headers (MFL login's Set-Cookie)."""
    if not NETWORK_ENABLED:
        raise NetworkDisabled(f"network call attempted while disabled: {url.split('?')[0]}")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "football_db_v2", **(headers or {})})
    return _open(req, timeout)


def post_json(url: str, body: bytes, timeout: int = 30) -> int:
    if not NETWORK_ENABLED:
        raise NetworkDisabled("network call attempted while disabled")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "football_db_v2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
