"""Platform installer registry and factory."""

from __future__ import annotations

from typing import List, Optional

from installer.core import env
from installer.platforms.base import PlatformInstaller

#: Manager name -> module-level constructor.
_MANAGERS = {
    "apt": "installer.platforms.linux:AptInstaller",
    "dnf": "installer.platforms.linux:DnfInstaller",
    "pacman": "installer.platforms.linux:PacmanInstaller",
    "zypper": "installer.platforms.linux:ZypperInstaller",
    "brew": "installer.platforms.macos:HomebrewInstaller",
    "pkg": "installer.platforms.termux:PkgInstaller",
    "winget": "installer.platforms.windows:WingetInstaller",
}


def _import(path: str):
    mod_name, _, cls_name = path.partition(":")
    import importlib

    return getattr(importlib.import_module(mod_name), cls_name)


def manager_name() -> str:
    """Canonical package-manager id for the current platform."""
    return env.package_manager()


def get_installer(log=None) -> Optional[PlatformInstaller]:
    """Return the right backend for this machine, or None when unsupported."""
    name = manager_name()
    if not name:
        return None
    entry = _MANAGERS.get(name)
    if not entry:
        return None
    return _import(entry)(log)


def supported_managers() -> List[str]:
    return list(_MANAGERS.keys())
