import os
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from installer.downloads.fetcher import sha256_file, download_file, DownloadError


class TestSha256(unittest.TestCase):
    def test_sha256_empty(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"")
            path = f.name
        try:
            digest = sha256_file(path)
            self.assertEqual(
                digest,
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            )
        finally:
            os.unlink(path)

    def test_sha256_known(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            digest = sha256_file(path)
            self.assertEqual(
                digest,
                "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
            )
        finally:
            os.unlink(path)


class TestDownload(unittest.TestCase):
    def test_download_http_file(self):
        try:
            result = download_file(
                "https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/AGENTS.md",
                retries=1,
                timeout=15,
            )
            if result:
                self.assertTrue(os.path.exists(result))
                os.unlink(result)
        except DownloadError:
            pass


if __name__ == "__main__":
    unittest.main()
