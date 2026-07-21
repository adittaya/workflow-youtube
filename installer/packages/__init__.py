"""
Package abstraction layer.
Maps package names to OS-specific install commands.
"""
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from installer.core.platform import PlatformInfo, detect


@dataclass
class PackageDefinition:
    name: str                      # Canonical name
    version_flag: str = "--version"
    version_extract: Optional[Callable[[str], str]] = None
    min_version: Optional[str] = None
    check_cmd: Optional[str] = None  # Binary name to check
    install_hint: str = ""
    linux: dict = field(default_factory=dict)
    macos: dict = field(default_factory=dict)
    windows: dict = field(default_factory=dict)
    termux: dict = field(default_factory=dict)


PACKAGE_DB: dict[str, PackageDefinition] = {}


def register(pkg: PackageDefinition):
    PACKAGE_DB[pkg.name] = pkg


def _extract_version_default(output: str) -> str:
    """Extract version from typical --version output."""
    import re
    for line in output.strip().split("\n"):
        # Match patterns like "v1.2.3", "1.2.3", "version 1.2.3"
        m = re.search(r'(\d+\.\d+\.\d+)', line)
        if m:
            return m.group(1)
    return ""


def _comp_version(v1: str, v2: str) -> int:
    """Compare two semver strings. Returns -1, 0, or 1."""
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        for a, b in zip(parts1, parts2):
            if a < b:
                return -1
            if a > b:
                return 1
        return 0
    except (ValueError, AttributeError):
        return 0


def _get_pm_install(info: PlatformInfo, pkg: PackageDefinition) -> str:
    pm = info.package_manager
    if info.os_name == "termux":
        return pkg.termux.get("install", f"pkg install {pkg.termux.get('pkg', pkg.name)}")
    if info.os_name == "darwin":
        return pkg.macos.get("install", f"brew install {pkg.macos.get('formula', pkg.name)}")
    if info.os_name == "windows":
        return pkg.windows.get("install", f"winget install {pkg.windows.get('winget_id', pkg.name)}")
    if pm == "apt":
        return pkg.linux.get("apt", f"apt install -y {pkg.linux.get('apt_pkg', pkg.name)}")
    if pm == "dnf":
        return pkg.linux.get("dnf", f"dnf install -y {pkg.linux.get('dnf_pkg', pkg.name)}")
    if pm == "pacman":
        return pkg.linux.get("pacman", f"pacman -S --noconfirm {pkg.linux.get('pacman_pkg', pkg.name)}")
    if pm == "zypper":
        return pkg.linux.get("zypper", f"zypper install -y {pkg.linux.get('zypper_pkg', pkg.name)}")
    if pm == "apk":
        return f"apk add {pkg.name}"
    if pm == "emerge":
        return f"emerge {pkg.name}"
    return ""


def get_package(name: str) -> Optional[PackageDefinition]:
    return PACKAGE_DB.get(name)


def is_installed(name: str) -> tuple[bool, str]:
    """Check if a package is installed. Returns (installed, version)."""
    pkg = get_package(name)
    if not pkg:
        return False, ""

    binary = pkg.check_cmd or name
    binary_path = shutil.which(binary)
    if not binary_path:
        return False, ""

    try:
        import shlex
        args = [binary_path] + shlex.split(pkg.version_flag)
        result = subprocess.run(
            args,
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout or result.stderr
        if pkg.version_extract:
            version = pkg.version_extract(output)
        else:
            version = _extract_version_default(output)
        return True, version
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return True, ""


def install(name: str, info: Optional[PlatformInfo] = None) -> bool:
    """Install a package using the platform's package manager."""
    if not info:
        info = detect()
    pkg = get_package(name)
    if not pkg:
        return False

    cmd = _get_pm_install(info, pkg)
    if not cmd:
        return False

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def check_version(name: str, min_version: Optional[str] = None) -> tuple[bool, str, bool]:
    """
    Check if a package is installed and meets minimum version.
    Returns (installed, version, meets_min).
    """
    installed, version = is_installed(name)
    if not installed:
        return False, "", False

    pkg = get_package(name)
    min_v = min_version or (pkg.min_version if pkg else None)
    if min_v and version:
        ok = _comp_version(version, min_v) >= 0
        return True, version, ok
    return True, version, True


def register_packages():
    """Register all known packages."""
    for pkg in _BUILTIN_PACKAGES:
        register(pkg)


_BUILTIN_PACKAGES = [
    PackageDefinition(
        name="git",
        version_flag="--version",
        linux={"apt": "apt install -y git", "dnf": "dnf install -y git",
               "pacman": "pacman -S --noconfirm git", "zypper": "zypper install -y git"},
        macos={"install": "brew install git"},
        windows={"install": "winget install Git.Git"},
        termux={"install": "pkg install git"},
    ),
    PackageDefinition(
        name="python3",
        check_cmd="python3",
        version_flag="--version",
        linux={"apt": "apt install -y python3 python3-pip",
               "dnf": "dnf install -y python3 python3-pip",
               "pacman": "pacman -S --noconfirm python python-pip",
               "zypper": "zypper install -y python3 python3-pip"},
        macos={"install": "brew install python@3"},
        windows={"install": "winget install Python.Python.3.12"},
        termux={"install": "pkg install python"},
    ),
    PackageDefinition(
        name="node",
        check_cmd="node",
        version_flag="--version",
        linux={"apt": "apt install -y nodejs npm",
               "dnf": "dnf install -y nodejs npm",
               "pacman": "pacman -S --noconfirm nodejs npm",
               "zypper": "zypper install -y nodejs npm"},
        macos={"install": "brew install node"},
        windows={"install": "winget install OpenJS.NodeJS.LTS"},
        termux={"install": "pkg install nodejs"},
    ),
    PackageDefinition(
        name="docker",
        check_cmd="docker",
        version_flag="--version",
        linux={"apt": "apt install -y docker.io",
               "dnf": "dnf install -y docker-ce docker-ce-cli",
               "pacman": "pacman -S --noconfirm docker",
               "zypper": "zypper install -y docker"},
        macos={"install": "brew install --cask docker"},
        windows={"install": "winget install Docker.DockerDesktop"},
    ),
    PackageDefinition(
        name="curl",
        version_flag="--version",
        linux={"apt": "apt install -y curl",
               "dnf": "dnf install -y curl",
               "pacman": "pacman -S --noconfirm curl",
               "zypper": "zypper install -y curl"},
        macos={"install": "brew install curl"},
        windows={"install": "winget install cURL.cURL"},
        termux={"install": "pkg install curl"},
    ),
    PackageDefinition(
        name="wget",
        version_flag="--version",
        linux={"apt": "apt install -y wget",
               "dnf": "dnf install -y wget",
               "pacman": "pacman -S --noconfirm wget",
               "zypper": "zypper install -y wget"},
        macos={"install": "brew install wget"},
        termux={"install": "pkg install wget"},
    ),
    PackageDefinition(
        name="java",
        check_cmd="java",
        version_flag="-version",
        min_version="11.0.0",
        linux={"apt": "apt install -y default-jre",
               "dnf": "dnf install -y java-11-openjdk",
               "pacman": "pacman -S --noconfirm jre-openjdk",
               "zypper": "zypper install -y java-11-openjdk"},
        macos={"install": "brew install --cask temurin"},
        windows={"install": "winget install EclipseAdoptium.Temurin.11.JRE"},
    ),
    PackageDefinition(
        name="code",
        check_cmd="code",
        version_flag="--version",
        linux={"apt": "apt install -y code",
               "dnf": "dnf install -y code",
               "pacman": "pacman -S --noconfirm code"},
        macos={"install": "brew install --cask visual-studio-code"},
        windows={"install": "winget install Microsoft.VisualStudioCode"},
    ),
    PackageDefinition(
        name="google-chrome",
        check_cmd="google-chrome-stable",
        version_flag="--version",
        linux={"apt": "apt install -y google-chrome-stable"},
        macos={"install": "brew install --cask google-chrome"},
        windows={"install": "winget install Google.Chrome"},
    ),
    PackageDefinition(
        name="chromium",
        version_flag="--version",
        linux={"apt": "apt install -y chromium-browser",
               "dnf": "dnf install -y chromium",
               "pacman": "pacman -S --noconfirm chromium"},
        termux={"install": "pkg install chromium"},
    ),
    PackageDefinition(
        name="selenium",
        check_cmd="python3",
        version_flag="-c \"import selenium; print(selenium.__version__)\"",
        version_extract=lambda o: o.strip(),
        linux={"apt": "pip3 install selenium"},
        macos={"install": "pip3 install selenium"},
        windows={"install": "pip install selenium"},
        termux={"install": "pip install selenium"},
    ),
    PackageDefinition(
        name="flask",
        check_cmd="python3",
        version_flag="-c \"import flask; print(flask.__version__)\"",
        version_extract=lambda o: o.strip(),
        linux={"apt": "pip3 install flask"},
        macos={"install": "pip3 install flask"},
        windows={"install": "pip install flask"},
        termux={"install": "pip install flask"},
    ),
    PackageDefinition(
        name="node",
        check_cmd="node",
        version_flag="--version",
        linux={"apt": "apt install -y nodejs npm",
               "dnf": "dnf install -y nodejs npm",
               "pacman": "pacman -S --noconfirm nodejs npm",
               "zypper": "zypper install -y nodejs npm"},
        macos={"install": "brew install node"},
        windows={"install": "winget install OpenJS.NodeJS.LTS"},
        termux={"install": "pkg install nodejs"},
    ),
    PackageDefinition(
        name="requests",
        check_cmd="python3",
        version_flag="-c \"import requests; print(requests.__version__)\"",
        version_extract=lambda o: o.strip(),
        linux={"apt": "pip3 install requests"},
        macos={"install": "pip3 install requests"},
        windows={"install": "pip install requests"},
        termux={"install": "pip install requests"},
    ),
    PackageDefinition(
        name="webdriver-manager",
        check_cmd="python3",
        version_flag="-c \"import webdriver_manager; print(webdriver_manager.__version__)\"",
        version_extract=lambda o: o.strip(),
        linux={"apt": "pip3 install webdriver-manager"},
        macos={"install": "pip3 install webdriver-manager"},
        windows={"install": "pip install webdriver-manager"},
        termux={"install": "pip install webdriver-manager"},
    ),
    PackageDefinition(
        name="pynacl",
        check_cmd="python3",
        version_flag="-c \"import nacl; print(nacl.__version__)\"",
        version_extract=lambda o: o.strip(),
        linux={"apt": "pip3 install pynacl"},
        macos={"install": "pip3 install pynacl"},
        windows={"install": "pip install pynacl"},
        termux={"install": "pip install pynacl"},
    ),
    PackageDefinition(
        name="urllib3",
        check_cmd="python3",
        version_flag="-c \"import urllib3; print(urllib3.__version__)\"",
        version_extract=lambda o: o.strip(),
        linux={"apt": "pip3 install urllib3"},
        macos={"install": "pip3 install urllib3"},
        windows={"install": "pip install urllib3"},
        termux={"install": "pip install urllib3"},
    ),
    PackageDefinition(
        name="npm",
        check_cmd="npm",
        version_flag="--version",
        linux={"apt": "apt install -y npm",
               "dnf": "dnf install -y npm",
               "pacman": "pacman -S --noconfirm npm",
               "zypper": "zypper install -y npm"},
        macos={"install": "brew install npm"},
        windows={"install": "winget install OpenJS.NodeJS.LTS"},
        termux={"install": "pkg install nodejs"},
    ),
]
