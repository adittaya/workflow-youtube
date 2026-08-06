"""Self-update: check GitHub Releases, compare versions, upgrade.

The installer installs a source copy of the project. ``installer update``
updates that copy — either with ``git pull`` when the install was from a clone,
or by downloading the latest source archive. Version checks use the GitHub
Releases API; when no release exists (this project ships from ``main``) the
main-branch archive is fetched instead.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from installer.core import utils
from installer.version import REPO

API = f"https://api.github.com/repos/{REPO}/releases/latest"
# The project ships from the `main` branch (no releases published), so archive
# updates fetch the same codeload tarball bootstrap.sh uses.
MAIN_TARBALL = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/main"


@dataclass
class Release:
    tag: str
    name: str
    body: str
    url: str
    published_at: str


def _version_key(value: str) -> tuple:
    digits = re.findall(r"\d+", value)
    return tuple(int(d) for d in digits)


def fetch_latest_release(log=None) -> Optional[Release]:
    """Fetch metadata for the newest GitHub release, or None on any failure."""
    try:
        req = urllib.request.Request(API, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "installer",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        if log:
            log.warn(f"could not check for updates: {exc}")
        return None
    return Release(
        tag=data.get("tag_name", ""),
        name=data.get("name", ""),
        body=data.get("body") or "",
        url=data.get("html_url", ""),
        published_at=data.get("published_at", ""),
    )


def is_newer(latest: Release, current: str) -> bool:
    return _version_key(latest.tag) > _version_key(current)


def changelog(release: Release, limit: int = 20) -> str:
    lines = [l for l in release.body.splitlines() if l.strip()]
    return "\n".join(lines[:limit])


def update_from_git(install_dir: Path, log=None) -> tuple[bool, str]:
    """Pull latest in a git working copy. Returns (success, message)."""
    if not (install_dir / ".git").exists():
        return False, "install is not a git clone; use release archive update"
    res = utils.run(["git", "-C", str(install_dir), "pull", "--ff-only"], capture=True)
    if res.returncode == 0:
        return True, (res.stdout or "updated").strip()
    return False, (res.stderr or "git pull failed").strip()


def update_from_archive(install_dir: Path, log=None) -> tuple[bool, str]:
    """Download the latest main-branch source and replace the copy."""
    from installer.downloads import Downloader, extract_archive

    url = MAIN_TARBALL
    dl = Downloader(log=log)
    tmp = install_dir / ".update.tmp" / "repo.tar.gz"
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        dl.download(url, tmp)
        target = install_dir / ".update.tmp" / "src"
        utils.remove_path(target)
        extract_archive(tmp, target)
        # Move new source over current one.
        new_src = next(p for p in target.iterdir() if p.is_dir()) if any(
            p.is_dir() for p in target.iterdir()) else target
        for item in new_src.iterdir():
            dest = install_dir / item.name
            utils.remove_path(dest)
            if item.is_dir():
                import shutil

                shutil.copytree(item, dest)
            else:
                import shutil

                shutil.copy2(item, dest)
        utils.remove_path(tmp.parent)
        return True, f"updated from {url}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def perform_update(install_dir: Path, log=None) -> tuple[bool, str]:
    if (install_dir / ".git").exists():
        return update_from_git(install_dir, log)
    return update_from_archive(install_dir, log)
