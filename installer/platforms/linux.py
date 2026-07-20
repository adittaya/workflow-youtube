from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Optional

from installer.core.executor import check_command, get_command_path, run_command
from installer.platforms.base import BasePlatform, PlatformInfo
from installer.interactive.ui import status


class LinuxPlatform(BasePlatform):

    PM_COMMANDS = {
        "apt": {
            "install": "DEBIAN_FRONTEND=noninteractive apt install -y {pkg}",
            "update": "apt update",
            "available": "apt-cache show {pkg}",
            "version": "apt-cache policy {pkg}",
            "version_re": r"Candidate:\s+(\S+)",
        },
        "dnf": {
            "install": "dnf install -y {pkg}",
            "update": "dnf check-update",
            "available": "dnf list available {pkg}",
            "version": "dnf info {pkg}",
            "version_re": r"Version\s*:\s*(\S+)",
        },
        "pacman": {
            "install": "pacman -S --noconfirm {pkg}",
            "update": "pacman -Sy",
            "available": "pacman -Ss ^{pkg}$",
            "version": "pacman -Qi {pkg}",
            "version_re": r"Version\s*:\s*(\S+)",
        },
        "zypper": {
            "install": "zypper install -y {pkg}",
            "update": "zypper refresh",
            "available": "zypper search {pkg}",
            "version": "zypper info {pkg}",
            "version_re": r"Version\s*:\s*(\S+)",
        },
    }

    @staticmethod
    def _read_os_release() -> dict[str, str]:
        info: dict[str, str] = {}
        for path in ("/etc/os-release", "/usr/lib/os-release"):
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                info[key.lower()] = value
            break
        return info

    @staticmethod
    def _detect_package_manager() -> str:
        os_rel = LinuxPlatform._read_os_release()
        distro_id = os_rel.get("id", "").lower()

        pm_map: dict[str, list[str]] = {
            "ubuntu": ["apt"],
            "debian": ["apt"],
            "linuxmint": ["apt"],
            "pop": ["apt"],
            "raspbian": ["apt"],
            "kali": ["apt"],
            "fedora": ["dnf"],
            "rhel": ["dnf"],
            "centos": ["dnf"],
            "rocky": ["dnf"],
            "alma": ["dnf"],
            "ol": ["dnf"],
            "arch": ["pacman"],
            "manjaro": ["pacman"],
            "artix": ["pacman"],
            "opensuse-leap": ["zypper"],
            "opensuse-tumbleweed": ["zypper"],
            "sles": ["zypper"],
            "alpine": ["apk"],
            "void": ["xbps-install"],
            "gentoo": ["emerge"],
            "slackware": ["slackpkg"],
        }

        candidates = pm_map.get(distro_id, [])
        for pm in candidates:
            if check_command(pm):
                return pm

        id_like = os_rel.get("id_like", "").lower()
        for token in id_like.split(","):
            token = token.strip()
            candidates = pm_map.get(token, [])
            for pm in candidates:
                if check_command(pm):
                    return pm

        for pm in ("apt", "dnf", "pacman", "zypper"):
            if check_command(pm):
                return pm

        return "unknown"

    @staticmethod
    def detect() -> PlatformInfo:
        os_rel = LinuxPlatform._read_os_release()
        distro_id = os_rel.get("id", "").lower() or os_rel.get("id_like", "").lower().split(",")[0].strip() or "unknown"
        version_id = os_rel.get("version_id", os_rel.get("version", platform.release()).split()[0])

        DISTRO_MAP: dict[str, str] = {
            "ubuntu": "ubuntu", "debian": "debian",
            "fedora": "fedora", "rhel": "fedora",
            "centos": "fedora", "rocky": "fedora",
            "alma": "fedora", "ol": "fedora",
            "arch": "arch", "manjaro": "arch",
            "artix": "arch", "endeavouros": "arch",
            "opensuse-leap": "opensuse",
            "opensuse-tumbleweed": "opensuse",
            "sles": "opensuse",
            "linuxmint": "ubuntu", "pop": "ubuntu",
            "raspbian": "debian", "kali": "debian",
            "alpine": "unknown",
        }
        distro_family = DISTRO_MAP.get(distro_id, "unknown")

        machine = platform.machine().lower()
        ARCH_MAP = {
            "x86_64": "x86_64", "amd64": "x86_64",
            "aarch64": "aarch64", "arm64": "aarch64",
            "armv7l": "armv7l", "armv6l": "armv6l",
            "i686": "i686", "i386": "i686",
        }
        arch = ARCH_MAP.get(machine, machine)

        pkg_manager = LinuxPlatform._detect_package_manager()

        has_sudo = check_command("sudo")

        wsl = False
        try:
            osrel = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8", errors="replace")
            if "microsoft" in osrel.lower() or "wsl" in osrel.lower() or os.environ.get("WSL_DISTRO_NAME"):
                wsl = True
        except OSError:
            pass

        docker = Path("/.dockerenv").exists()

        shell_path = os.environ.get("SHELL", "")
        shell = Path(shell_path).stem.lower() if shell_path else "bash"

        home = os.path.expanduser("~")
        user = os.environ.get("USER", os.environ.get("LOGNAME", "unknown"))

        profile_map: dict[str, str] = {
            "bash": ".bashrc",
            "zsh": ".zshrc",
            "fish": ".config/fish/config.fish",
            "sh": ".profile",
        }
        shell_profile = os.path.join(home, profile_map.get(shell, ".profile"))

        return PlatformInfo(
            name="linux",
            distribution=distro_family,
            version=version_id,
            arch=arch,
            package_manager=pkg_manager,
            has_sudo=has_sudo,
            is_wsl=wsl,
            is_docker=docker,
            config_dir=os.path.join(home, ".config", "vplink3"),
            data_dir=os.path.join(home, ".local", "share", "vplink3"),
            cache_dir=os.path.join(home, ".cache", "vplink3"),
            shell=shell,
            shell_profile=shell_profile,
            home=home,
            user=user,
        )

    @staticmethod
    def install_package(pkg_name: str, sudo: bool = True) -> bool:
        pm = LinuxPlatform.detect().package_manager
        templ = LinuxPlatform.PM_COMMANDS.get(pm, {}).get("install")
        if not templ:
            return False
        cmd = templ.format(pkg=pkg_name)
        if sudo:
            cmd = f"sudo {cmd}"
        result = run_command(cmd, timeout=300)
        return result.success

    @staticmethod
    def install_google_chrome(sudo: bool = True) -> bool:
        """Install Google Chrome on Debian/Ubuntu via official repo (handles deps)."""
        arch = platform.machine().lower()
        if "aarch64" in arch or "arm64" in arch:
            status("No official Google Chrome for arm64 — skipping", "warn")
            return False

        prefix = "sudo" if sudo else ""

        status("Adding Google Chrome repository...")
        keyring = "/usr/share/keyrings/google-chrome.gpg"
        # Download signing key
        r1 = run_command(
            f"wget -q -O /tmp/google-chrome-key.asc https://dl.google.com/linux/linux_signing_key.pub",
            timeout=30,
        )
        if not r1.success:
            r1 = run_command(
                f"curl -fsSL -o /tmp/google-chrome-key.asc https://dl.google.com/linux/linux_signing_key.pub",
                timeout=30,
            )
        if r1.success:
            run_command(f"{prefix} gpg --dearmor -o {keyring} < /tmp/google-chrome-key.asc 2>/dev/null", timeout=15)
            run_command(
                f'{prefix} sh -c \'echo "deb [arch=amd64 signed-by={keyring}] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list\'',
                timeout=10,
            )
            run_command(f"{prefix} apt update", timeout=120)
        else:
            # Fallback: direct .deb download
            import tempfile
            deb_url = "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
            tmp = tempfile.mktemp(suffix=".deb")
            try:
                status("Downloading Google Chrome .deb...")
                r = run_command(f"wget -q -O {tmp} {deb_url}", timeout=120)
                if not r.success:
                    r = run_command(f"curl -fsSL -o {tmp} {deb_url}", timeout=120)
                if r.success:
                    run_command(f"{prefix} dpkg -i {tmp} 2>/dev/null; {prefix} apt-get install -f -y -q", timeout=120)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        # Attempt the actual install
        status("Installing google-chrome-stable...")
        run_command(f"{prefix} DEBIAN_FRONTEND=noninteractive apt install -y google-chrome-stable", timeout=180)

        installed = os.path.exists("/usr/bin/google-chrome") or os.path.exists("/usr/bin/google-chrome-stable")
        if installed:
            status("Google Chrome installed", "ok")
        return installed

    @staticmethod
    def update_package_index(sudo: bool = True) -> bool:
        pm = LinuxPlatform.detect().package_manager
        templ = LinuxPlatform.PM_COMMANDS.get(pm, {}).get("update")
        if not templ:
            return False
        cmd = templ.format(pkg="")
        if sudo:
            cmd = f"sudo {cmd}"
        result = run_command(cmd, timeout=120)
        return result.success

    @staticmethod
    def package_available(pkg_name: str) -> bool:
        pm = LinuxPlatform.detect().package_manager
        templ = LinuxPlatform.PM_COMMANDS.get(pm, {}).get("available")
        if not templ:
            return False
        cmd = templ.format(pkg=pkg_name)
        result = run_command(cmd, timeout=30)
        return result.success

    @staticmethod
    def get_package_version(pkg_name: str) -> Optional[str]:
        pm = LinuxPlatform.detect().package_manager
        entry = LinuxPlatform.PM_COMMANDS.get(pm)
        if not entry:
            return None
        templ = entry.get("version")
        version_re = entry.get("version_re")
        if not templ or not version_re:
            return None
        cmd = templ.format(pkg=pkg_name)
        result = run_command(cmd, timeout=30)
        if not result.success:
            return None
        match = re.search(version_re, result.stdout)
        if match:
            return match.group(1)
        return None
