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

    def dpkg_configure_all(self, dry_run: bool = False) -> bool:
        """Finish configuring every half-configured package."""
        if dry_run:
            return True
        return self._run(["dpkg", "--configure", "-a"], capture=True).returncode == 0

    def fix_broken(self, dry_run: bool = False) -> bool:
        """Resolve broken dependency state (``apt-get -f install``)."""
        if dry_run:
            return True
        return self._run(["apt-get", "-f", "install", "-y"], capture=True).returncode == 0

    def purge(self, packages: List[str], dry_run: bool = False) -> bool:
        """Remove a package AND its dpkg state (stale-entry images keep state
        after the files were pruned). Falls back to ``dpkg --force-all -P``."""
        if dry_run:
            return True
        res = self._run(["apt-get", "remove", "-y", "--purge"] + packages, capture=True)
        if res.returncode == 0:
            return True
        for pkg in packages:
            self._run(["dpkg", "--force-all", "-P", pkg], capture=True)
        return True

    def heal(self, packages: List[str], dry_run: bool = False) -> bool:
        """Repair a stale/broken dpkg state without removing the package:
        finish half-configured packages, resolve broken dependencies, then
        force ``--reinstall``. Callers re-verify the tool binaries on PATH
        after this and escalate to ``purge_and_reinstall`` if needed."""
        if dry_run:
            return True
        self.dpkg_configure_all()
        self.fix_broken()
        return self.reinstall(packages)

    def purge_and_reinstall(self, packages: List[str], dry_run: bool = False) -> bool:
        """Nuclear option for images where dpkg state says 'installed' but the
        files were pruned (Cloud Shell): remove the package + state, refresh
        indexes, then install fresh so apt actually unpacks everything."""
        if dry_run:
            return True
        self.purge(packages)
        self.update()
        return self.install(packages)

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
