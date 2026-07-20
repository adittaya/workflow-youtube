from typing import Optional, Callable
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import hashlib
import os
import time
from pathlib import Path
from installer.core.executor import run_command

class DownloadError(Exception):
    pass

class ChecksumError(DownloadError):
    pass

def sha256_file(path: str) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def download_file(
    url: str,
    dest: Optional[str] = None,
    expected_sha256: Optional[str] = None,
    retries: int = 3,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: int = 120,
) -> Optional[str]:
    """
    Download a file with retry and optional SHA256 verification.
    Returns the destination path on success, None on failure.
    """
    if dest is None:
        dest = os.path.basename(url.split("?")[0]) or "download"

    dest_path = Path(dest)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": "VPLink-Installer/3.0",
                "Accept": "*/*",
            })

            with urlopen(req, timeout=timeout) as response:
                total = int(response.headers.get("Content-Length", 0))
                downloaded = 0

                with open(temp_path, "wb") as f:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total:
                            progress_callback(downloaded, total)

                if total > 0 and downloaded != total:
                    raise DownloadError(f"Downloaded {downloaded} bytes, expected {total}")

            # Verify checksum
            if expected_sha256:
                actual = sha256_file(str(temp_path))
                if actual.lower() != expected_sha256.lower():
                    temp_path.unlink(missing_ok=True)
                    raise ChecksumError(f"SHA256 mismatch: expected {expected_sha256}, got {actual}")

            # Rename temp to final
            temp_path.rename(dest_path)
            return str(dest_path)

        except (URLError, HTTPError, DownloadError, ChecksumError) as e:
            temp_path.unlink(missing_ok=True)
            if attempt < retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
            else:
                raise DownloadError(f"Failed to download {url} after {retries} attempts: {e}")

    return None

def download_github_release(
    repo: str,
    asset_pattern: str,
    dest_dir: str,
    version: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """
    Download a release asset from GitHub.
    repo: "owner/repo"
    asset_pattern: glob pattern for asset name (e.g., "*.tar.gz")
    """
    import json

    if version:
        api_url = f"https://api.github.com/repos/{repo}/releases/tags/{version}"
    else:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"

    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "VPLink-Installer/3.0"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = Request(api_url, headers=headers)
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        if "assets" not in data:
            # Try tag-based response
            for key in ("assets", "zipball_url", "tarball_url"):
                if key in data:
                    url = data.get(key)
                    if url:
                        return download_file(url, os.path.join(dest_dir, os.path.basename(url)))
            return None

        import fnmatch
        for asset in data.get("assets", []):
            if fnmatch.fnmatch(asset["name"], asset_pattern):
                download_url = asset["browser_download_url"]
                dest = os.path.join(dest_dir, asset["name"])
                return download_file(download_url, dest)

        raise DownloadError(f"No asset matching '{asset_pattern}' found in release")

    except Exception as e:
        raise DownloadError(f"GitHub release download failed: {e}")

def download_extract_archive(url: str, dest_dir: str, archive_type: Optional[str] = None) -> Optional[str]:
    """
    Download and extract an archive (zip/tar.gz) to dest_dir.
    Returns the extraction directory path.
    """
    import tempfile
    import shutil

    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = download_file(url, dest=os.path.join(tmp, "archive"))
        if not archive_path:
            return None

        if archive_path.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(str(dest_path))
        elif archive_path.endswith((".tar.gz", ".tgz")):
            import tarfile
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(str(dest_path))
        elif archive_path.endswith(".tar.bz2"):
            import tarfile
            with tarfile.open(archive_path, "r:bz2") as tf:
                tf.extractall(str(dest_path))
        elif archive_path.endswith(".tar.xz"):
            import tarfile
            with tarfile.open(archive_path, "r:xz") as tf:
                tf.extractall(str(dest_path))
        else:
            shutil.copy2(archive_path, str(dest_path))

    return str(dest_path)
