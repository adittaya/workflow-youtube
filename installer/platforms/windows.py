"""Windows package manager backend (Winget).

Winget runs fine directly from a console, so ``installer install`` uses it
in-process. ``install.ps1`` additionally bootstraps Python via Winget before
the Python installer can run, since the installer itself requires Python.
"""

from __future__ import annotations

from typing import List

from installer.core import utils
from installer.platforms.base import PlatformInstaller


class WingetInstaller(PlatformInstaller):
    name = "winget"
    #: Programmatic mode used so no interactive UAC prompts block automation.
    FLAGS = [
        "--disable-interactivity",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        ok = True
        for pkg in packages:
            argv = ["winget", "install", "--id", pkg, "--exact"] + self.FLAGS
            if pkg.startswith("msstore:"):
                argv = ["winget", "install", pkg, "--source", "msstore"] + self.FLAGS
            if dry_run:
                continue
            if utils.run(argv, capture=True, timeout=1800).returncode != 0:
                ok = False
        return ok

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        ok = True
        for pkg in packages:
            argv = ["winget", "uninstall", "--id", pkg, "--exact", "--silent"]
            if dry_run:
                continue
            if utils.run(argv, capture=True, timeout=1800).returncode != 0:
                ok = False
        return ok

    def update(self, dry_run: bool = False) -> bool:
        if dry_run:
            return True
        return utils.run(["winget", "upgrade", "--accept-source-agreements"],
                         capture=True, timeout=1800).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return f"Run in PowerShell: winget install {' '.join(packages)}"


def windows_installer(log=None) -> WingetInstaller:
    return WingetInstaller(log)
