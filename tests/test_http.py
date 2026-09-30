"""Phase 8: transport retries in fdb.http (the only network path). Offline."""
import io
import unittest
import urllib.error
from unittest import mock

from fdb import http


class Resp:
    status, headers = 200, {}

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Retries(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(http, "RETRY_WAITS", (0, 0, 0, 0)), mock.patch.object(http.time, "sleep")]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_dns_failure_then_success_is_retried(self):
        errs = [urllib.error.URLError("[Errno 11001] getaddrinfo failed"), ConnectionResetError(10054, "forcibly closed")]
        def fake(req, timeout):
            if errs:
                raise errs.pop(0)
            return Resp(b"ok")
        with mock.patch.object(http.urllib.request, "urlopen", side_effect=fake):
            self.assertEqual(http.get("https://example.test/x"), b"ok")

    def test_http_error_response_is_not_retried(self):
        calls = []
        def fake(req, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'"Game not found"'))
        with mock.patch.object(http.urllib.request, "urlopen", side_effect=fake):
            with self.assertRaises(urllib.error.HTTPError):
                http.request("https://example.test/all22/game/1")
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_the_last_wait(self):
        calls = []
        def fake(req, timeout):
            calls.append(1)
            raise urllib.error.URLError("getaddrinfo failed")
        with mock.patch.object(http.urllib.request, "urlopen", side_effect=fake):
            with self.assertRaises(urllib.error.URLError):
                http.get("https://example.test/x")
        self.assertEqual(len(calls), 5)

    def test_disabled_network_is_never_retried_or_counted(self):
        with mock.patch.object(http, "NETWORK_ENABLED", False):
            before = http.CALLS
            with self.assertRaises(http.NetworkDisabled):
                http.get("https://example.test/x")
            self.assertEqual(http.CALLS, before)


if __name__ == "__main__":
    unittest.main()
