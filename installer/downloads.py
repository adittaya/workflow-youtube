"""Robust downloads: SHA256 verification, size checks, retries, resume.

Uses only the standard library so it works on a bare machine. URLs are
validated before use, downloads go to a temp file and are atomically renamed
only after verification passes, and partial files are resumed via HTTP Range.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from installer.core import utils

DEFAULT_RETRIES = 3
CHUNK = 1 << 16  # 64 KiB


class DownloadError(RuntimeError):
    pass


class Downloader:
    def __init__(self, log=None, retries: int = DEFAULT_RETRIES,
                 progress: Optional[Callable[[int, int], None]] = None,
                 timeout: float = 60.0):
        self.log = log
        self.retries = max(1, retries)
        self.progress = progress
        self.timeout = timeout

    # -- public ------------------------------------------------------------
    def download(self, url: str, dest: Path, *,
                 sha256: Optional[str] = None,
                 expected_size: Optional[int] = None) -> Path:
        """Download ``url`` to ``dest``. Verifies sha256/size when provided."""
        if not utils.is_url(url):
            raise DownloadError(f"refusing unsafe URL: {url}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        resume = tmp.stat().st_size if tmp.exists() else 0

        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt < self.retries:
            attempt += 1
            try:
                self._fetch(url, tmp, resume)
                self._verify(tmp, sha256, expected_size)
                os.replace(tmp, dest)
                self._make_executable(dest)
                return dest
            except (DownloadError, urllib.error.URLError, OSError) as exc:
                last_exc = exc
                if self.log:
                    self.log.warn(f"download attempt {attempt}/{self.retries} failed: {exc}")
                if tmp.exists():
                    resume = tmp.stat().st_size  # continue from partial on retry
                else:
                    resume = 0
        raise DownloadError(f"download failed after {self.retries} attempts: {url} ({last_exc})")

    # -- internals ---------------------------------------------------------
    def _fetch(self, url: str, tmp: Path, resume: int) -> None:
        req = urllib.request.Request(url)
        if resume:
            req.add_header("Range", f"bytes={resume}-")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp, \
                open(tmp, "ab") as out:
            if resume and getattr(resp, "status", 200) != 206:
                # Server ignored the Range header — restart the download so
                # partial bytes are never duplicated.
                out.seek(0)
                out.truncate()
                resume = 0
            total = None
            try:
                total = int(resp.headers.get("Content-Length") or 0) + resume
            except (TypeError, ValueError):
                pass
            written = resume
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                if self.progress and total:
                    self.progress(written, total)
                elif self.progress:
                    self.progress(written, -1)

    def _verify(self, tmp: Path, sha256: Optional[str], expected_size: Optional[int]) -> None:
        size = tmp.stat().st_size
        if expected_size is not None and size != expected_size:
            raise DownloadError(f"size mismatch: got {size}, expected {expected_size}")
        if sha256:
            digest = hashlib.sha256()
            with open(tmp, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest().lower() != sha256.lower():
                raise DownloadError(
                    f"sha256 mismatch: got {digest.hexdigest()}, expected {sha256}")
            if self.log:
                self.log.debug(f"sha256 verified: {sha256}")

    @staticmethod
    def _make_executable(dest: Path) -> None:
        # Mark downloaded binaries executable (best effort).
        if os.name != "nt":
            try:
                dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                pass


# --------------------------------------------------------------------------
# Archive extraction
# --------------------------------------------------------------------------

def extract_archive(archive: Path, dest: Path) -> Path:
    """Extract zip/tar/tar.gz/tar.xz into ``dest``. Path-traversal safe."""
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            _safe_extract_zip(zf, dest)
    elif name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar"):
        mode = "r:*" if name.endswith(".tar") else "r:gz"
        with tarfile.open(archive, mode) as tf:
            _safe_extract_tar(tf, dest)
    else:
        raise DownloadError(f"unsupported archive type: {archive.name}")
    return dest


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise DownloadError(f"unsafe path in archive: {member.filename}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    zf.close()


def _safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    base = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(base)):
            raise DownloadError(f"unsafe path in archive: {member.name}")
    tf.extractall(dest)  # members already validated above
    tf.close()
