"""
Download module. Supports GitHub releases, ZIP, TAR, executables, config files.
Features: SHA256 verification, retry, resume, progress.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from installer import logging as log


def download(url: str, dest: str, sha256: Optional[str] = None,
             retry: int = 3, on_progress: Optional[Callable] = None) -> bool:
    """Download a file from URL to destination path."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retry + 1):
        try:
            log.info(f"Downloading {url} → {dest}")
            resp = requests.get(url, stream=True, timeout=30, allow_redirects=True)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress and total:
                            on_progress(downloaded / total)

            if sha256:
                if not verify_sha256(dest, sha256):
                    log.error(f"SHA256 mismatch for {dest}")
                    if attempt < retry:
                        continue
                    return False

            log.success(f"Downloaded: {dest}")
            return True

        except requests.RequestException as e:
            log.warn(f"Download attempt {attempt}/{retry} failed: {e}")
            if attempt < retry:
                import time
                time.sleep(2)
            else:
                log.error(f"Download failed after {retry} attempts: {url}")
                return False
    return False


def download_github_release(repo: str, asset: str, dest: str,
                            tag: Optional[str] = None, sha256: Optional[str] = None) -> bool:
    """Download a release asset from GitHub."""
    if tag:
        url = f"https://github.com/{repo}/releases/download/{tag}/{asset}"
    else:
        url = f"https://github.com/{repo}/releases/latest/download/{asset}"
    return download(url, dest, sha256)


def extract_archive(path: str, dest_dir: str, archive_type: Optional[str] = None) -> bool:
    """Extract an archive (zip, tar.gz, tar.bz2, tar.xz)."""
    path_obj = Path(path)
    dest_obj = Path(dest_dir)
    dest_obj.mkdir(parents=True, exist_ok=True)

    suffix = archive_type or "".join(path_obj.suffixes)

    try:
        if suffix.endswith(".zip") or ".zip" in suffix:
            shutil.unpack_archive(str(path_obj), str(dest_obj), "zip")
        elif suffix.endswith((".tar.gz", ".tgz")):
            shutil.unpack_archive(str(path_obj), str(dest_obj), "gztar")
        elif suffix.endswith((".tar.bz2", ".tbz2")):
            shutil.unpack_archive(str(path_obj), str(dest_obj), "bztar")
        elif suffix.endswith((".tar.xz", ".txz")):
            shutil.unpack_archive(str(path_obj), str(dest_obj), "xztar")
        elif suffix.endswith(".tar"):
            shutil.unpack_archive(str(path_obj), str(dest_obj), "tar")
        else:
            log.error(f"Unknown archive type: {suffix}")
            return False
        log.success(f"Extracted: {path} → {dest_dir}")
        return True
    except (shutil.ReadError, OSError) as e:
        log.error(f"Extraction failed: {e}")
        return False


def verify_sha256(path: str, expected: str) -> bool:
    """Verify SHA256 checksum of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual = h.hexdigest()
        ok = actual.lower() == expected.lower()
        if not ok:
            log.error(f"SHA256 mismatch: expected {expected}, got {actual}")
        return ok
    except OSError as e:
        log.error(f"Cannot verify SHA256: {e}")
        return False


def verify_size(path: str, expected_bytes: int) -> bool:
    """Verify file size matches expected."""
    try:
        actual = Path(path).stat().st_size
        ok = actual == expected_bytes
        if not ok:
            log.warn(f"Size mismatch: expected {expected_bytes}, got {actual}")
        return ok
    except OSError:
        return False


def validate_url(url: str) -> bool:
    """Validate that a URL is safe to download from."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def make_executable(path: str):
    """Make a file executable on Unix-like systems."""
    try:
        os.chmod(path, os.stat(path).st_mode | 0o111)
        log.debug(f"Made executable: {path}")
    except OSError as e:
        log.warn(f"Cannot make executable: {e}")
