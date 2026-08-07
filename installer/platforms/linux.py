"""Linux package managers: apt, dnf, pacman and zypper."""

from __future__ import annotations

from typing import List

from installer.core import utils
from installer.platforms.base import PlatformInstaller


class AptInstaller(PlatformInstaller):
    name = "apt"

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        argv = ["apt-get", "install", "-y"] + packages
        if dry_run:
            return True
        res = self._run(argv, capture=True)
        return res.returncode == 0

    def reinstall(self, packages: List[str], dry_run: bool = False) -> bool:
        """Force a reinstall. Some images ship a stale dpkg entry: plain
        ``apt-get install`` exits 0 ("already newest") without restoring the
        binary, leaving the tool missing. ``--reinstall`` forces it."""
        argv = ["apt-get", "install", "-y", "--reinstall"] + packages
        if dry_run:
            return True
        res = self._run(argv, capture=True)
        return res.returncode == 0

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["apt-get", "remove", "-y"] + packages, capture=True).returncode == 0

    def update(self, dry_run: bool = False) -> bool:
        return self._run(["apt-get", "update", "-y"], capture=True).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return f"Run: sudo apt-get install -y {' '.join(packages)}"


class DnfInstaller(PlatformInstaller):
    name = "dnf"

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["dnf", "install", "-y"] + packages, capture=True).returncode == 0

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["dnf", "remove", "-y"] + packages, capture=True).returncode == 0

    def update(self, dry_run: bool = False) -> bool:
        return self._run(["dnf", "makecache"], capture=True).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return f"Run: sudo dnf install -y {' '.join(packages)}"


class PacmanInstaller(PlatformInstaller):
    name = "pacman"

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["pacman", "-S", "--noconfirm", "--needed"] + packages, capture=True).returncode == 0

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["pacman", "-R", "--noconfirm"] + packages, capture=True).returncode == 0

    def update(self, dry_run: bool = False) -> bool:
        return self._run(["pacman", "-Sy", "--noconfirm"], capture=True).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return f"Run: sudo pacman -S --noconfirm --needed {' '.join(packages)}"


class ZypperInstaller(PlatformInstaller):
    name = "zypper"

    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["zypper", "--non-interactive", "install"] + packages, capture=True).returncode == 0

    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        return self._run(["zypper", "--non-interactive", "remove"] + packages, capture=True).returncode == 0

    def update(self, dry_run: bool = False) -> bool:
        return self._run(["zypper", "refresh"], capture=True).returncode == 0

    def error_hint(self, packages: List[str]) -> str:
        return f"Run: sudo zypper --non-interactive install {' '.join(packages)}"


def detect_linux_installer(log=None) -> PlatformInstaller:
    """Pick a Linux backend from the detected package manager."""
    from installer.core.env import package_manager

    pm = package_manager()
    if pm == "dnf":
        return DnfInstaller(log)
    if pm == "pacman":
        return PacmanInstaller(log)
    if pm == "zypper":
        return ZypperInstaller(log)
    # apt is the default fallback on Debian-like distros.
    if utils.which("apt-get"):
        return AptInstaller(log)
    return DnfInstaller(log)


def is_distro_supported() -> bool:
    from installer.core.env import distro_id, distro_like

    supported = {"ubuntu", "debian", "fedora", "arch", "opensuse",
                 "opensuse-leap", "opensuse-tumbleweed", "linuxmint", "pop",
                 "neon", "kali", "manjaro", "endeavouros"}
    return distro_id() in supported or "debian" in distro_like() or "fedora" in distro_like()
