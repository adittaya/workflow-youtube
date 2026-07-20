import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request

from installer.core.executor import run_command
from installer.logging.logger import get_logger
from installer.interactive.ui import status, confirm

log = get_logger("update")

def check_for_update(current_version: str = "3.0.0") -> Optional[str]:
    try:
        req = Request(
            "https://api.github.com/repos/adittaya/VPLINK-3.0/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "VPLink-Installer/3.0"},
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        latest = data.get("tag_name", "").lstrip("v")
        if not latest:
            return None

        def ver_tuple(v: str):
            parts = v.split(".")
            return tuple(int(p) if p.isdigit() else 0 for p in parts)

        if ver_tuple(latest) > ver_tuple(current_version):
            return latest

        return None
    except Exception as e:
        log.warning(f"Failed to check for update: {e}")
        return None

def perform_update() -> bool:
    script_dir = Path(__file__).resolve().parent.parent.parent
    git_dir = script_dir / ".git"

    if git_dir.exists():
        status("Updating via git pull...", "wait")
        result = run_command(["git", "pull"], cwd=str(script_dir), timeout=60)
        if result.success:
            status("Updated via git pull", "ok")
            log.info(f"Git pull output: {result.stdout[:200]}")
            return True
        log.warning(f"Git pull failed: {result.stderr[:200]}")

    status("Downloading latest release from GitHub...", "wait")
    from installer.downloads.fetcher import download_extract_archive
    url = "https://github.com/adittaya/VPLINK-3.0/archive/refs/heads/main.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        extracted = download_extract_archive(url, tmp)
        if not extracted:
            status("Failed to download update", "error")
            return False

        import shutil
        source = Path(extracted) / "VPLINK-3.0-main"
        if source.exists():
            for item in source.iterdir():
                dest = script_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            status("Updated from GitHub archive", "ok")
            return True

    return False

def do_update() -> bool:
    status("Checking for updates...", "wait")
    latest = check_for_update()

    if latest is None:
        status("Already up to date", "ok")
        log.info("No update available")
        return True

    status(f"Update available: v{latest}", "info")
    if not confirm(f"Upgrade to v{latest}?"):
        log.info("Update declined by user")
        return False

    if perform_update():
        status(f"Updated to v{latest}", "ok")
        log.info(f"Update to v{latest} completed")
        return True
    else:
        status("Update failed", "error")
        log.error("Update failed")
        return False
