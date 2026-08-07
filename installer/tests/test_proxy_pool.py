"""Tests for proxy-pool download rotation (candidate_urls, mark_blocked and
the download_video loop that rotates across pool proxies).

No network is used: the pool REST calls and live probes are patched out.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import download_helpers
import proxy_pool


def _row(ip, port=9999, proto="http", latency=100, e2=True):
    return {"ip": ip, "port": port, "proto": proto, "latency_ms": latency, "e2_ok": e2}


class CandidateUrlsTests(unittest.TestCase):
    def _patch_pool(self, enabled=True, configured=True, rows=None):
        rows = rows if rows is not None else []
        return (
            mock.patch.object(proxy_pool, "is_enabled", return_value=enabled),
            mock.patch.object(proxy_pool, "is_configured", return_value=configured),
            mock.patch.object(proxy_pool, "list_pool", return_value=rows),
            mock.patch.object(proxy_pool, "_used_unexpired", return_value=set()),
        )

    def test_empty_when_pool_disabled(self):
        with self._patch_pool(enabled=False)[0]:
            self.assertEqual(proxy_pool.candidate_urls(), [])

    def test_empty_when_not_configured(self):
        with self._patch_pool(configured=False)[1]:
            self.assertEqual(proxy_pool.candidate_urls(), [])

    def test_empty_when_pool_unreachable(self):
        with mock.patch.object(proxy_pool, "list_pool", side_effect=OSError("boom")):
            self.assertEqual(proxy_pool.candidate_urls(), [])

    def test_orders_by_latency_and_skips_used(self):
        rows = [_row("slow", latency=500), _row("fast", latency=50)]
        with mock.patch.object(proxy_pool, "list_pool", return_value=rows), \
                mock.patch.object(proxy_pool, "_used_unexpired", return_value={("slow", 9999)}):
            self.assertEqual(proxy_pool.candidate_urls(),
                             ["http://fast:9999"])

    def test_respects_limit_and_dedups(self):
        rows = [_row(f"p{i}", latency=100 + i) for i in range(6)]
        with mock.patch.object(proxy_pool, "list_pool", return_value=rows):
            urls = proxy_pool.candidate_urls(limit=3)
            self.assertEqual(len(urls), 3)
            self.assertEqual(urls[0], "http://p0:9999")

    def test_orders_fastest_first(self):
        rows = [_row("slow", latency=500), _row("fast", latency=50)]
        with mock.patch.object(proxy_pool, "list_pool", return_value=rows):
            self.assertEqual(proxy_pool.candidate_urls(),
                             ["http://fast:9999", "http://slow:9999"])

    def test_falls_back_to_all_when_everything_used(self):
        rows = [_row("p1"), _row("p2")]
        with mock.patch.object(proxy_pool, "list_pool", return_value=rows), \
                mock.patch.object(proxy_pool, "_used_unexpired",
                                  return_value={("p1", 9999), ("p2", 9999)}):
            self.assertEqual(proxy_pool.candidate_urls(limit=2),
                             ["http://p1:9999", "http://p2:9999"])

    def test_ignores_dead_proxies(self):
        rows = [_row("dead", e2=False), _row("alive")]
        with mock.patch.object(proxy_pool, "list_pool", return_value=rows):
            self.assertEqual(proxy_pool.candidate_urls(), ["http://alive:9999"])

    def test_default_candidate_urls_has_no_cap(self):
        rows = [_row(f"p{i}", latency=100 + i) for i in range(20)]
        with mock.patch.object(proxy_pool, "is_enabled", return_value=True), \
                mock.patch.object(proxy_pool, "is_configured", return_value=True), \
                mock.patch.object(proxy_pool, "list_pool", return_value=rows):
            self.assertEqual(len(proxy_pool.candidate_urls()), 20)


class MarkBlockedTests(unittest.TestCase):
    def test_parses_url_and_parks(self):
        with mock.patch.object(proxy_pool, "_mark_used") as mu:
            proxy_pool.mark_blocked("http://1.2.3.4:8080")
            mu.assert_called_once_with("1.2.3.4", 8080)

    def test_ignores_bad_url(self):
        with mock.patch.object(proxy_pool, "_mark_used") as mu:
            proxy_pool.mark_blocked("not-a-url")
            mu.assert_not_called()


class DownloadVideoRotationTests(unittest.TestCase):
    def setUp(self):
        self._data = tempfile.mkdtemp(prefix="yt-mirror-test-")
        self._old_env = os.environ.copy()
        os.environ["YT_DATA_DIR"] = self._data
        os.environ.pop("YT_PROXY", None)
        os.environ.pop("WORKING_PROXIES", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_rotates_to_next_pool_proxy_until_success(self):
        results = {"http://p1": "bot_check", "http://p2": "bot_check",
                   "http://p3": "ok"}
        tried = []
        parked = []

        def fake_try(url, out, proxy):
            tried.append(proxy)
            kind = results.get(proxy, "error")
            if kind == "ok":
                return {"path": "/tmp/video.mp4", "info": {}}, "ok"
            return None, kind

        with mock.patch.object(proxy_pool, "candidate_urls",
                               return_value=["http://p1", "http://p2", "http://p3"]), \
                mock.patch.object(proxy_pool, "ensure_working", return_value=None), \
                mock.patch.object(proxy_pool, "mark_blocked",
                                  side_effect=lambda u: parked.append(u)), \
                mock.patch.object(download_helpers, "_try_download", fake_try):
            result = download_helpers.download_video("https://youtu.be/x")
            self.assertEqual(result["path"], "/tmp/video.mp4")
            self.assertEqual(tried, ["http://p1", "http://p2", "http://p3"])
            self.assertEqual(parked, ["http://p1", "http://p2"])

    def test_raises_bot_check_after_all_rotated(self):
        tried = []

        def fake_try(url, out, proxy):
            tried.append(proxy)
            return None, "bot_check"

        with mock.patch.object(proxy_pool, "candidate_urls",
                               return_value=["http://p1", "http://p2"]), \
                mock.patch.object(proxy_pool, "ensure_working", return_value=None), \
                mock.patch.object(proxy_pool, "mark_blocked"), \
                mock.patch.object(download_helpers, "_try_download", fake_try):
            with self.assertRaises(download_helpers.YouTubeBotCheck):
                download_helpers.download_video("https://youtu.be/x")
            self.assertEqual(tried, ["http://p1", "http://p2"])

    def test_no_pool_still_plain_failure(self):
        with mock.patch.object(proxy_pool, "candidate_urls", return_value=[]), \
                mock.patch.object(proxy_pool, "ensure_working", return_value=None), \
                mock.patch.object(download_helpers, "_try_download",
                                  return_value=(None, "error")):
            self.assertIsNone(download_helpers.download_video(
                "https://youtu.be/x", tempfile.mkdtemp()))

    def test_pool_refresh_retry_loop_no_limit(self):
        """Pool enabled: after every proxy fails, the pool is refreshed and a
        new round is tried (no retry limit)."""
        candidate_rounds = iter([["http://p1"], ["http://p2"]])
        tried = []
        refreshes = []

        def fake_try(url, out, proxy):
            tried.append(proxy)
            if proxy == "http://p2":
                return {"path": "/tmp/video.mp4", "info": {}}, "ok"
            return None, "bot_check"

        with mock.patch.object(proxy_pool, "is_enabled", return_value=True), \
                mock.patch.object(proxy_pool, "candidate_urls",
                                  side_effect=lambda: next(candidate_rounds)), \
                mock.patch.object(proxy_pool, "ensure_working", return_value=None), \
                mock.patch.object(proxy_pool, "mark_blocked"), \
                mock.patch.object(proxy_pool, "refresh_and_activate",
                                  side_effect=lambda: refreshes.append(1)), \
                mock.patch.object(download_helpers, "_try_download", fake_try):
            result = download_helpers.download_video("https://youtu.be/x")
            self.assertEqual(result["path"], "/tmp/video.mp4")
            self.assertEqual(tried, ["http://p1", "http://p2"])
            self.assertEqual(len(refreshes), 1)

    def test_pool_refresh_respects_pool_retries_cap(self):
        candidate_rounds = iter([["http://p1"], ["http://p1"]])
        refreshes = []

        def fake_try(url, out, proxy):
            return None, "bot_check"

        with mock.patch.object(proxy_pool, "is_enabled", return_value=True), \
                mock.patch.object(proxy_pool, "candidate_urls",
                                  side_effect=lambda: next(candidate_rounds)), \
                mock.patch.object(proxy_pool, "ensure_working", return_value=None), \
                mock.patch.object(proxy_pool, "mark_blocked"), \
                mock.patch.object(proxy_pool, "refresh_and_activate",
                                  side_effect=lambda: refreshes.append(1)), \
                mock.patch.object(download_helpers, "_try_download", fake_try):
            with self.assertRaises(download_helpers.YouTubeBotCheck):
                download_helpers.download_video("https://youtu.be/x", pool_retries=1)
            self.assertEqual(len(refreshes), 1)


if __name__ == "__main__":
    unittest.main()
