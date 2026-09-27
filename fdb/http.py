"""The only way code in this package touches the network.

`fdb rebuild` sets NETWORK_ENABLED = False, so a rebuild that tries to fetch
fails loudly instead of quietly depending on the network (REBUILD_DESIGN §2.2)."""
import urllib.request

NETWORK_ENABLED = True
CALLS = 0


class NetworkDisabled(RuntimeError):
    pass


def get(url: str, headers: dict | None = None, timeout: int = 120) -> bytes:
    global CALLS
    if not NETWORK_ENABLED:
        raise NetworkDisabled(f"network call attempted while disabled: {url}")
    CALLS += 1
    req = urllib.request.Request(url, headers={"User-Agent": "football_db_v2", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def request(url: str, data: bytes | None = None, headers: dict | None = None,
            timeout: int = 60) -> tuple[int, object, bytes]:
    """-> (status, response headers, body). Raises urllib.error.HTTPError on 4xx/5xx.
    For callers that need response headers (MFL login's Set-Cookie)."""
    global CALLS
    if not NETWORK_ENABLED:
        raise NetworkDisabled(f"network call attempted while disabled: {url.split('?')[0]}")
    CALLS += 1
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "football_db_v2", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()


def post_json(url: str, body: bytes, timeout: int = 30) -> int:
    if not NETWORK_ENABLED:
        raise NetworkDisabled("network call attempted while disabled")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "football_db_v2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
