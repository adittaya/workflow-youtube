"""
Self-update module.
Checks GitHub Releases for newer versions and performs upgrades.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests

from installer import logging as log


GITHUB_REPO = "adittaya/workflow-vplink"
VERSION = "1.0.0"


def get_current_version() -> str:
    return VERSION


def check_latest() -> Optional[str]:
    """Check GitHub Releases for the latest version tag."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github+json"}
        )
        if resp.status_code == 200:
            return resp.json().get("tag_name", "")
    except requests.RequestException:
        pass
    return None


def get_changelog(tag: str) -> str:
    """Get release notes for a specific tag."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}",
            timeout=10,
            headers={"Accept": "application/vnd.github+json"}
        )
        if resp.status_code == 200:
            return resp.json().get("body", "")
    except requests.RequestException:
        pass
    return ""


def update_self() -> bool:
    """Pull the latest code from the repository."""
    repo_root = Path(__file__).parent.parent.parent
    try:
        log.info(f"Pulling latest from {GITHUB_REPO}")
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=str(repo_root),
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            log.success(f"Updated: {result.stdout.strip()[:200]}")
            return True
        else:
            log.error(f"Update failed: {result.stderr[:300]}")
            return False
    except Exception as e:
        log.error(f"Update error: {e}")
        return False


def compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Returns -1, 0, or 1."""
    try:
        parts1 = [int(x) for x in v1.lstrip("v").split(".")]
        parts2 = [int(x) for x in v2.lstrip("v").split(".")]
        for a, b in zip(parts1, parts2):
            if a < b: return -1
            if a > b: return 1
        return 0
    except (ValueError, AttributeError):
        return 0
