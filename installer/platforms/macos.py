"""macOS package manager backend (Homebrew)."""

from __future__ import annotations

import os
from typing import List

from installer.core import utils
from installer.platforms.base import PlatformInstaller

BREW_ENV = {
    "HOMEBREW_NO_AUTO_UPDATE": "1",
    "HOMEBREW_NO_ANALYTICS": "1",
    "HOMEBREW_NO_INSTALL_CLEANUP": "1",
}


class HomebrewInstaller(PlatformInstaller):
    name = "brew"

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        argv = ["brew", "install"] + packages
        if dry_run:
            return True
        env = {**os.environ, **BREW_ENV}
        return utils.run(argv, capture=True, env=env, timeout=1800).returncode == 0

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        return utils.run(["brew", "uninstall"] + packages, capture=True).returncode == 0

    def update(self, dry_run: bool = False) -> bool:
        env = {**os.environ, **BREW_ENV}
        return utils.run(["brew", "update"], capture=True, env=env).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return (
            f"Run: brew install {' '.join(packages)}\n"
            "If Homebrew is missing, install it first:\n"
            '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        )


def macos_installer(log=None) -> HomebrewInstaller:
    return HomebrewInstaller(log)
