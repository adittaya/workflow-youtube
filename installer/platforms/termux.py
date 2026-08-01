"""Termux package manager backend (``pkg``)."""

from __future__ import annotations

from typing import List

from installer.core import utils
from installer.platforms.base import PlatformInstaller


class PkgInstaller(PlatformInstaller):
    name = "pkg"

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        argv = ["pkg", "install", "-y"] + packages
        if dry_run:
            return True
        return utils.run(argv, capture=True, timeout=1800).returncode == 0

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        return utils.run(["pkg", "uninstall", "-y"] + packages, capture=True).returncode == 0

    def update(self, dry_run: bool = False) -> bool:
        return utils.run(["pkg", "update"], capture=True, timeout=1800).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return f"Run: pkg install -y {' '.join(packages)}"


def termux_installer(log=None) -> PkgInstaller:
    return PkgInstaller(log)
