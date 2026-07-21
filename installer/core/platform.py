"""
Platform detection module.
Auto-detects OS, distribution, architecture, shell, package manager, and privileges.
"""
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PlatformInfo:
    os_name: str = ""           # linux, darwin, windows, termux
    distribution: str = ""      # ubuntu, debian, fedora, arch, opensuse, macos, windows, termux
    dist_version: str = ""
    arch: str = ""              # x86_64, aarch64, armv7l, i686
    shell: str = ""             # bash, zsh, fish, powershell
    package_manager: str = ""   # apt, dnf, pacman, zypper, brew, winget, pkg
    is_root: bool = False
    is_wsl: bool = False
    is_docker: bool = False
    has_systemd: bool = False
    home: str = ""
    config_dir: str = ""
    data_dir: str = ""
    bin_dir: str = ""

    env: dict = field(default_factory=dict)


def detect() -> PlatformInfo:
    info = PlatformInfo()

    system = platform.system().lower()
    info.arch = platform.machine().lower()
    info.home = str(Path.home())

    # OS detection
    if "termux" in str(Path.home()).lower() or os.environ.get("TERMUX_VERSION"):
        info.os_name = "termux"
        info.distribution = "termux"
        info.package_manager = "pkg"
        info.shell = _detect_shell(info.home)
        info.is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
        info.config_dir = f"{info.home}/.config/vplink"
        info.data_dir = f"{info.home}/.local/share/vplink"
        info.bin_dir = f"{info.home}/../usr/bin"
        return info

    if system == "windows":
        info.os_name = "windows"
        info.distribution = "windows"
        info.arch = os.environ.get("PROCESSOR_ARCHITECTURE", info.arch)
        info.package_manager = "winget" if shutil.which("winget") else "choco" if shutil.which("choco") else ""
        info.shell = _detect_windows_shell()
        info.config_dir = os.environ.get("APPDATA", f"{info.home}/AppData/Roaming") + "/vplink"
        info.data_dir = os.environ.get("LOCALAPPDATA", f"{info.home}/AppData/Local") + "/vplink"
        info.bin_dir = f"{info.home}\\vplink\\bin"
        return info

    if system == "darwin":
        info.os_name = "darwin"
        info.distribution = "macos"
        info.package_manager = "brew" if shutil.which("brew") else "port" if shutil.which("port") else ""
        info.shell = _detect_shell(info.home)
        info.is_root = os.geteuid() == 0
        info.is_wsl = os.environ.get("WSL_DISTRO_NAME", "") != ""
        info.config_dir = f"{info.home}/.config/vplink"
        info.data_dir = f"{info.home}/.local/share/vplink"
        info.bin_dir = "/usr/local/bin"
        return info

    # Linux
    info.os_name = "linux"
    info.is_root = os.geteuid() == 0
    info.is_wsl = os.environ.get("WSL_DISTRO_NAME", "") != ""
    info.is_docker = _check_docker()
    info.has_systemd = shutil.which("systemctl") is not None
    info.shell = _detect_shell(info.home)
    info.config_dir = f"{info.home}/.config/vplink"
    info.data_dir = f"{info.home}/.local/share/vplink"
    info.bin_dir = "/usr/local/bin" if info.is_root else f"{info.home}/.local/bin"

    info.distribution, info.dist_version = _detect_linux_dist()
    info.package_manager = _detect_package_manager(info.distribution)

    return info


def _detect_shell(home: str) -> str:
    shell = os.environ.get("SHELL", "").lower()
    if "zsh" in shell:
        return "zsh"
    if "fish" in shell:
        return "fish"
    if "bash" in shell:
        return "bash"
    # Check common profiles
    for p in [f"{home}/.zshrc", f"{home}/.bashrc", f"{home}/.config/fish/config.fish"]:
        if Path(p).exists():
            if "zsh" in p:
                return "zsh"
            if "bash" in p:
                return "bash"
            if "fish" in p:
                return "fish"
    return "bash"


def _detect_windows_shell():
    ps = os.environ.get("PSModulePath", "")
    if ps:
        return "powershell"
    return "cmd"


def _detect_linux_dist() -> tuple:
    """Detect Linux distribution and version."""
    # Try /etc/os-release first
    try:
        with open("/etc/os-release") as f:
            data = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip('"')
        dist = data.get("ID", "").lower()
        ver = data.get("VERSION_ID", "")
        return dist, ver
    except FileNotFoundError:
        pass

    # Try /etc/lsb-release
    try:
        with open("/etc/lsb-release") as f:
            for line in f:
                if line.startswith("DISTRIB_ID"):
                    return line.split("=")[1].strip().lower(), ""
    except FileNotFoundError:
        pass

    # Fallback
    return platform.system().lower(), ""


def _detect_package_manager(dist: str) -> str:
    mapping = {
        "ubuntu": "apt", "debian": "apt", "linuxmint": "apt",
        "fedora": "dnf", "rhel": "dnf", "centos": "dnf",
        "arch": "pacman", "manjaro": "pacman", "endeavouros": "pacman",
        "opensuse": "zypper", "suse": "zypper",
        "alpine": "apk",
        "void": "xbps",
        "gentoo": "emerge",
        "slackware": "slackpkg",
    }
    if dist in mapping:
        pm = mapping[dist]
        if shutil.which(pm):
            return pm

    # Fallback: detect by availability
    for pm in ["apt", "dnf", "pacman", "zypper", "apk", "xbps", "emerge"]:
        if shutil.which(pm):
            return pm
    return ""


def _check_docker() -> bool:
    if not shutil.which("docker"):
        return False
    # Check if we're inside a container
    try:
        with open("/proc/1/cgroup") as f:
            content = f.read()
            return "docker" in content or "containerd" in content
    except FileNotFoundError:
        pass
    try:
        with open("/proc/1/sched") as f:
            content = f.read()
            return "docker" in content
    except FileNotFoundError:
        pass
    return False


def is_supported() -> bool:
    info = detect()
    supported = {
        "linux": ["ubuntu", "debian", "fedora", "arch", "opensuse",
                  "linuxmint", "rhel", "centos", "manjaro", "alpine"],
        "darwin": ["macos"],
        "windows": ["windows"],
        "termux": ["termux"],
    }
    return info.distribution in supported.get(info.os_name, [])


def suggest_install() -> str:
    info = detect()
    if info.distribution in ("ubuntu", "debian", "linuxmint"):
        return "sudo apt update && sudo apt install -y"
    if info.distribution in ("fedora", "rhel", "centos"):
        return "sudo dnf install -y"
    if info.distribution in ("arch", "manjaro", "endeavouros"):
        return "sudo pacman -S --noconfirm"
    if info.distribution == "opensuse":
        return "sudo zypper install -y"
    if info.distribution == "alpine":
        return "sudo apk add"
    if info.os_name == "darwin":
        return "brew install"
    if info.os_name == "windows":
        return "winget install"
    if info.os_name == "termux":
        return "pkg install"
    return ""
