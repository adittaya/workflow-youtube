"""Unit tests for the yt-dlp download path (download_helpers / bgm_manager).

These tests only exercise pure logic: cookie resolution, command building,
bot-check detection and proxy-candidate ordering. They never invoke yt-dlp or
touch the real ~/.yt-mirror state.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in os.sys.path:
    os.sys.path.insert(0, _ROOT)

import download_helpers


class CookiesArgTests(unittest.TestCase):
    def setUp(self):
        self._data = tempfile.mkdtemp(prefix="yt-mirror-test-")
        self._old_env = os.environ.copy()
        os.environ.pop("YT_COOKIES", None)
        os.environ.pop("YT_COOKIES_FILE", None)
        os.environ["YT_DATA_DIR"] = self._data

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_no_cookies_configured(self):
        self.assertIsNone(download_helpers._cookies_arg())

    def test_yt_cookies_file_wins(self):
        p = Path(tempfile.mkdtemp()) / "cookies.txt"
        p.write_text("# Netscape HTTP Cookie File\n")
        os.environ["YT_COOKIES_FILE"] = str(p)
        self.assertEqual(download_helpers._cookies_arg(), str(p))

    def test_missing_yt_cookies_file_falls_back_to_secret(self):
        os.environ["YT_COOKIES_FILE"] = "/does/not/exist/cookies.txt"
        os.environ["YT_COOKIES"] = "# Netscape HTTP Cookie File\nfoo"
        resolved = download_helpers._cookies_arg()
        self.assertEqual(resolved, os.path.join(self._data, "cookies.txt"))
        self.assertTrue(os.path.exists(resolved))

    def test_yt_cookies_secret_materialized(self):
        os.environ["YT_COOKIES"] = "# Netscape HTTP Cookie File\nbar"
        resolved = download_helpers._cookies_arg()
        self.assertEqual(Path(resolved).read_text(), "# Netscape HTTP Cookie File\nbar\n")

    def test_settings_cookies_file_used(self):
        settings = Path(self._data) / "settings.json"
        settings.write_text(json.dumps({"cookies_file": "/tmp/exists-cookies.txt"}))
        # a path that does not exist must be ignored, not returned
        self.assertIsNone(download_helpers._cookies_arg())


class CookiesBrowserTests(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.copy()
        os.environ.pop("YT_COOKIES_BROWSER", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_env_var(self):
        os.environ["YT_COOKIES_BROWSER"] = "chrome"
        self.assertEqual(download_helpers._cookies_browser_arg(), "chrome")

    def test_none(self):
        self.assertIsNone(download_helpers._cookies_browser_arg())


class BotCheckTests(unittest.TestCase):
    def test_sign_in_wall_detected(self):
        self.assertTrue(download_helpers.is_bot_check(
            "ERROR: [youtube] abc: Sign in to confirm you're not a bot"))

    def test_unusual_traffic_detected(self):
        self.assertTrue(download_helpers.is_bot_check(
            "ERROR: unusual traffic detected"))

    def test_other_errors_not_bot_check(self):
        self.assertFalse(download_helpers.is_bot_check(
            "ERROR: [youtube] Video unavailable"))


class ProxyCandidatesTests(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.copy()
        self._data = tempfile.mkdtemp(prefix="yt-mirror-test-")
        os.environ["YT_DATA_DIR"] = self._data
        os.environ.pop("YT_PROXY", None)
        os.environ.pop("WORKING_PROXIES", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_working_proxies_env(self):
        os.environ["WORKING_PROXIES"] = json.dumps(["http://p1", "http://p2"])
        self.assertEqual(download_helpers.get_proxy_candidates(),
                         ["http://p1", "http://p2"])

    def test_working_proxies_deduped(self):
        os.environ["WORKING_PROXIES"] = json.dumps(["http://p1", "http://p1"])
        self.assertEqual(download_helpers.get_proxy_candidates(), ["http://p1"])

    def test_yt_proxy_fallback(self):
        os.environ["YT_PROXY"] = "http://single"
        self.assertEqual(download_helpers.get_proxy_candidates(), ["http://single"])

    def test_none(self):
        self.assertEqual(download_helpers.get_proxy_candidates(), [])


class RunYtDlpTests(unittest.TestCase):
    def setUp(self):
        self._data = tempfile.mkdtemp(prefix="yt-mirror-test-")
        self._old_env = os.environ.copy()
        os.environ.pop("YT_COOKIES", None)
        os.environ.pop("YT_COOKIES_FILE", None)
        os.environ["YT_DATA_DIR"] = self._data

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def _fake(self, code=0, stderr=""):
        return subprocess.CompletedProcess(["yt-dlp"], code, stdout="{}", stderr=stderr)

    def test_download_video_raises_bot_check_after_all_proxies(self):
        real = download_helpers._try_download
        calls = []

        def fake_try(url, out, proxy):
            calls.append(proxy)
            return None, "bot_check"

        download_helpers._try_download = fake_try
        os.environ["WORKING_PROXIES"] = json.dumps(["http://p1", "http://p2"])
        try:
            with self.assertRaises(download_helpers.YouTubeBotCheck):
                download_helpers.download_video("https://youtu.be/abc", tempfile.mkdtemp())
        finally:
            download_helpers._try_download = real
        self.assertEqual(calls, ["http://p1", "http://p2"])

    def test_download_video_returns_none_on_plain_failure(self):
        real = download_helpers._try_download
        os.environ["WORKING_PROXIES"] = json.dumps(["http://p1"])

        def fake_try(url, out, proxy):
            return None, "error"

        download_helpers._try_download = fake_try
        try:
            self.assertIsNone(download_helpers.download_video(
                "https://youtu.be/abc", tempfile.mkdtemp()))
        finally:
            download_helpers._try_download = real


if __name__ == "__main__":
    unittest.main()
