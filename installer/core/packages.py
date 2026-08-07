"""Package abstraction layer.

A logical package (e.g. ``git``) is mapped to the concrete package name(s) for
every supported package manager. ``install_package("git")`` transparently runs
``apt install git``, ``dnf install git``, ``brew install git``, ``winget install
Git.Git``, ``pkg install git`` or ``pacman -S git`` depending on the platform.

Definitions live in ``installer/packages.yaml`` so new tools can be added
without touching code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from installer.core.config import _load_yaml
from installer.core import env, utils


@dataclass
class Package:
    name: str
    systems: Dict[str, List[str]] = field(default_factory=dict)
    pip: Optional[str] = None
    verify: Optional[str] = None
    description: str = ""
    optional: bool = False
    min_version: Optional[str] = None

    def system_package_names(self, manager: str) -> List[str]:
        return self.systems.get(manager, [])

    def pip_package(self) -> Optional[str]:
        return self.pip


@dataclass
class PipPackage:
    name: str
    description: str = ""
    optional: bool = False
    verify: Optional[str] = None


class PackageRegistry:
    """In-memory registry of Package/PipPackage definitions."""

    def __init__(self):
        self._by_name: Dict[str, Package] = {}
        self._pip: List[PipPackage] = []

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_yaml(cls, path: Path) -> "PackageRegistry":
        text = path.read_text(encoding="utf-8")
        return cls.from_dict(_load_yaml(text))

    @classmethod
    def from_dict(cls, data: dict) -> "PackageRegistry":
        reg = cls()
        for name, raw in data.get("packages", {}).items():
            if not isinstance(raw, dict):
                continue
            pkg = Package(
                name=name,
                systems={k: list(v) for k, v in raw.get("systems", {}).items()},
                pip=raw.get("pip"),
                verify=raw.get("verify"),
                description=raw.get("description", ""),
                optional=bool(raw.get("optional", False)),
                min_version=raw.get("min_version"),
            )
            reg._by_name[name] = pkg
        for name, raw in data.get("pip_packages", {}).items():
            reg._pip.append(
                PipPackage(
                    name=name,
                    description=raw.get("description", "") if isinstance(raw, dict) else "",
                    optional=bool(raw.get("optional", False)) if isinstance(raw, dict) else False,
                    verify=raw.get("verify") if isinstance(raw, dict) else None,
                )
            )
        return reg

    # -- queries -----------------------------------------------------------
    def get(self, name: str) -> Optional[Package]:
        return self._by_name.get(name)

    def all(self) -> List[Package]:
        return list(self._by_name.values())

    def names(self) -> List[str]:
        return list(self._by_name.keys())

    def pip_packages(self) -> List[PipPackage]:
        return self._pip

    def verify_names(self) -> List[str]:
        """Binary names used to verify the full install (system + pip)."""
        names = [p.verify for p in self._by_name.values() if p.verify]
        names += [p.verify for p in self._pip if p.verify]
        return [n for n in names if n]

    # -- installation helpers ----------------------------------------------
    def system_install_names(self, manager: str, names: List[str]) -> List[str]:
        """Concrete package names to hand to ``manager`` for logical ``names``."""
        concrete: List[str] = []
        missing: List[str] = []
        for name in names:
            pkg = self.get(name)
            if not pkg:
                missing.append(name)
                continue
            mapped = pkg.system_package_names(manager)
            if mapped:
                concrete.extend(mapped)
            else:
                missing.append(name)
        return concrete, missing

    def pip_install_names(self, names: List[str]) -> List[str]:
        return [p.pip for p in self._pip if p.name in names and p.pip]


def parse_version(value: str) -> tuple:
    m = re.search(r"(\d+(?:\.\d+)+)", value or "")
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split(".")[:3])


def version_meets(installed: str, minimum: str) -> bool:
    if not minimum:
        return True
    return parse_version(installed) >= parse_version(minimum)


def check_package(registry: PackageRegistry, name: str) -> dict:
    """Return {'installed': bool, 'version': str|None, 'min_ok': bool}."""
    pkg = registry.get(name)
    verify = pkg.verify if pkg else name
    if name == "python":
        # The interpreter the tooling runs under *is* the installer's python,
        # and pip must be present so the app's dependencies can be installed.
        # (Fresh images often ship python3 without python3-pip.)
        version = env.python_version()
        installed = env.python_meets_minimum() and env.pip_version() is not None
    else:
        version = env.version_of(verify) if verify else None
        installed = version is not None or (pkg and pkg.pip and utils.which(verify))
    min_ok = True
    if pkg and pkg.min_version and version:
        min_ok = version_meets(version, pkg.min_version)
    return {
        "name": name,
        "verify": verify,
        "installed": bool(installed),
        "version": version,
        "min_version": pkg.min_version if pkg else None,
        "min_ok": min_ok,
        "optional": bool(pkg.optional) if pkg else False,
    }
