"""Tests for the downloader using a local HTTP server.

No external network is used: a ThreadingHTTPServer serves a temp directory on
127.0.0.1 and the downloader fetches from it.
"""

import hashlib
import http.server
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

from installer.downloads import DownloadError, Downloader

BODY = b"hello downloader payload 0123456789" * 40

_SERVE_DIR = None


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=_SERVE_DIR, **kwargs)

    def log_message(self, *args):
        pass


class DownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _SERVE_DIR
        cls._tmp = Path(tempfile.mkdtemp())
        cls._file = cls._tmp / "asset.bin"
        cls._file.write_bytes(BODY)
        cls._sha = hashlib.sha256(BODY).hexdigest()
        _SERVE_DIR = str(cls._tmp)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        cls._server = Server(("127.0.0.1", 0), _Handler)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls._base = f"http://127.0.0.1:{cls._server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()

    def _dl(self):
        dest = Path(tempfile.mkdtemp()) / "out.bin"
        return dest

    def test_download_ok(self):
        dest = self._dl()
        Downloader(retries=2).download(f"{self._base}/asset.bin", dest)
        self.assertEqual(dest.read_bytes(), BODY)

    def test_sha256_verified(self):
        dest = self._dl()
        Downloader().download(f"{self._base}/asset.bin", dest, sha256=self._sha)
        self.assertTrue(dest.exists())

    def test_wrong_sha_raises(self):
        dest = self._dl()
        with self.assertRaises(DownloadError):
            Downloader(retries=1).download(f"{self._base}/asset.bin", dest,
                                           sha256="0" * 64)

    def test_size_mismatch_raises(self):
        dest = self._dl()
        with self.assertRaises(DownloadError):
            Downloader(retries=1).download(f"{self._base}/asset.bin", dest,
                                           expected_size=1)

    def test_resume_from_partial(self):
        base = Path(tempfile.mkdtemp())
        final = base / "out.bin"
        part = final.with_suffix(final.suffix + ".part")
        part.write_bytes(BODY[:100])  # pretend a previous download was interrupted
        Downloader().download(f"{self._base}/asset.bin", final)
        self.assertEqual(final.read_bytes(), BODY)

    def test_unsafe_url_rejected(self):
        with self.assertRaises(DownloadError):
            Downloader().download("file:///etc/passwd", Path("/tmp/x"))

    def test_bad_url_fails_with_retries(self):
        dest = self._dl()
        with self.assertRaises(DownloadError):
            Downloader(retries=2).download("http://127.0.0.1:1/nope", dest)


if __name__ == "__main__":
    unittest.main()
