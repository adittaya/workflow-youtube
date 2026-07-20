"""Cross-platform environment detection for VPLink 3.0 installer.

Detects OS, distribution, architecture, package manager, shell, root,
WSL, Docker, and Termux environments.  Pure stdlib — no external deps.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class OSInfo:
    """Immutable snapshot of the current operating-system environment."""

    system: str          # Linux | Darwin | Windows | Termux
    distribution: str    # ubuntu, debian, fedora, arch, opensuse, macos, windows, termux
    version: str         # e.g. "22.04", "14", "11"
    arch: str            # x86_64, aarch64, armv7l
    package_manager: str # apt, dnf, pacman, zypper, brew, winget, pkg, choco, unknown
    shell: str           # bash, zsh, fish, powershell, cmd, unknown
    is_root: bool
    is_wsl: bool
    is_docker: bool
    is_termux: bool

    # -- convenience helpers ---------------------------------------------------

    @property
    def is_linux(self) -> bool:
        return self.system == "Linux"

    @property
    def is_macos(self) -> bool:
        return self.system == "Darwin"

    @property
    def is_windows(self) -> bool:
        return self.system == "Windows"

    @property
    def is_debian_family(self) -> bool:
        return self.distribution in ("ubuntu", "debian", "linuxmint", "pop",
                                     "raspbian", "kali", "elemntary")

    @property
    def is_redhat_family(self) -> bool:
        return self.distribution in ("fedora", "rhel", "centos", "rocky",
                                     "alma", "ol", "scientific")

    def describe(self) -> str:
        parts = [f"{self.system} {self.distribution} {self.version} ({self.arch})"]
        parts.append(f"pkg={self.package_manager} shell={self.shell}")
        flags = []
        if self.is_root:
            flags.append("root")
        if self.is_wsl:
            flags.append("wsl")
        if self.is_docker:
            flags.append("docker")
        if self.is_termux:
            flags.append("termux")
        if flags:
            parts.append("[" + ", ".join(flags) + "]")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _read_text(path: str | Path, default: str = "") -> str:
    """Read a text file, returning *default* on any error."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def _run_cmd(args: list[str], timeout: float = 5) -> str:
    """Run a command and return stdout, swallowing all errors."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""


def _check_cmd(name: str) -> bool:
    """Return True if *name* is found on PATH."""
    return shutil.which(name) is not None


def _os_release() -> dict[str, str]:
    """Parse /etc/os-release into a dict (lowercase keys, unquoted values)."""
    info: dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        text = _read_text(path)
        if text:
            break
    else:
        return info

    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        info[key.lower()] = value
    return info


def _detect_system() -> str:
    """Return one of Linux, Darwin, Windows, Termux."""
    if os.environ.get("TERMUX_VERSION"):
        return "Termux"
    system = platform.system()
    if system in ("Linux", "Darwin", "Windows"):
        return system
    return "Linux"  # best-effort fallback


def _detect_distribution(system: str, os_rel: dict[str, str]) -> str:
    """Return a normalised distribution identifier."""
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    if system == "Termux":
        return "termux"

    # Linux — prefer os-release
    if os_rel:
        id_ = os_rel.get("id", "").lower()
        id_like = os_rel.get("id_like", "").lower()

        known = {
            "ubuntu", "debian", "fedora", "arch", "manjaro",
            "opensuse-leap", "opensuse-tumbleweed", "sles",
            "centos", "rhel", "rocky", "alma", "ol",
            "linuxmint", "pop", "raspbian", "kali", "alpine",
            "void", "gentoo", "slackware", "artix",
        }
        if id_ in known:
            return id_
        # heuristic: map derivatives to their family
        for token in id_like.split(","):
            token = token.strip()
            if token in known:
                return token

    # Fallback heuristics without os-release
    if _check_cmd("apt"):
        return "debian"
    if _check_cmd("dnf"):
        return "fedora"
    if _check_cmd("pacman"):
        return "arch"
    if _check_cmd("zypper"):
        return "opensuse"
    return "unknown"


def _detect_version(os_rel: dict[str, str], distribution: str) -> str:
    """Extract a human-readable version string."""
    if distribution in ("macos", "windows", "termux", "unknown"):
        return platform.release()

    if os_rel:
        # Prefer VERSION_ID (short), fall back to VERSION
        ver = os_rel.get("version_id", "")
        if ver:
            return ver
        ver = os_rel.get("version", "")
        # Strip everything after the first space
        if ver:
            return ver.split()[0]

    return platform.release()


def _detect_arch() -> str:
    """Return the machine architecture in canonical form."""
    machine = platform.machine().lower()
    mapping = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "armv7l": "armv7l",
        "armv6l": "armv6l",
        "i686": "i686",
        "i386": "i686",
    }
    return mapping.get(machine, machine)


def _detect_package_manager(system: str, distribution: str) -> str:
    """Detect the primary system package manager."""
    # Explicit order per distro
    pm_priority: dict[str, list[str]] = {
        "debian": ["apt", "apt-get"],
        "ubuntu": ["apt", "apt-get"],
        "linuxmint": ["apt"],
        "pop": ["apt"],
        "raspbian": ["apt"],
        "kali": ["apt"],
        "fedora": ["dnf", "yum"],
        "rhel": ["dnf", "yum"],
        "centos": ["dnf", "yum"],
        "rocky": ["dnf", "yum"],
        "alma": ["dnf", "yum"],
        "ol": ["dnf", "yum"],
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

    if system == "Darwin":
        return "brew" if _check_cmd("brew") else "unknown"
    if system == "Windows":
        for cmd in ("winget", "choco", "scoop"):
            if _check_cmd(cmd):
                return cmd
        return "unknown"
    if system == "Termux":
        return "pkg"

    # Linux
    candidates = pm_priority.get(distribution, [])
    for pm in candidates:
        if _check_cmd(pm):
            return pm

    # Generic fallback scan
    for pm in ("apt", "dnf", "pacman", "zypper", "apk", "xbps-install"):
        if _check_cmd(pm):
            return pm

    return "unknown"


def _detect_shell() -> str:
    """Detect the user's primary shell."""
    # Windows
    if platform.system() == "Windows":
        ps = os.environ.get("PSModulePath", "")
        if ps:
            return "powershell"
        return "cmd"

    # Termux default
    if os.environ.get("TERMUX_VERSION"):
        return "bash"

    # SHELL env var (most reliable on Unix)
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        shell_name = Path(shell_path).name.lower()
        if shell_name in ("bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh"):
            return shell_name

    # Last resort: parse /etc/shells or parent process
    return "unknown"


def _detect_root() -> bool:
    """Return True if running as root."""
    if platform.system() == "Windows":
        # Windows doesn't have geteuid; check via whoami
        user = os.environ.get("USERNAME", "").lower()
        return user == "administrator" or _run_cmd(["whoami"], timeout=3) == "nt authority\\system"
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _detect_wsl() -> bool:
    """Return True if running inside Windows Subsystem for Linux."""
    # Check uname -r for Microsoft/WSL
    release = _read_text("/proc/sys/kernel/osrelease", "")
    if "microsoft" in release.lower() or "wsl" in release.lower():
        return True

    # Check environment variable
    if os.environ.get("WSL_DISTRO_NAME"):
        return True

    # Check cgroup v1
    cgroup = _read_text("/proc/1/cgroup", "")
    if "wsl" in cgroup.lower():
        return True

    return False


def _detect_docker() -> bool:
    """Return True if running inside a Docker container."""
    # /.dockerenv is the most reliable indicator
    if Path("/.dockerenv").exists():
        return True

    # Check /proc/1/cgroup for docker/containerd/lxc
    cgroup = _read_text("/proc/1/cgroup", "")
    if cgroup:
        for line in cgroup.splitlines():
            lower = line.lower()
            if any(tok in lower for tok in ("docker", "containerd", "lxc", "kubepods")):
                return True

    # Check /proc/1/sched for container indicators
    sched = _read_text("/proc/1/sched", "")
    if "init" not in sched and "systemd" not in sched and sched:
        # PID 1 is not init/systemd — likely a container entrypoint
        if cgroup:
            return True

    # OCI container env vars
    if os.environ.get("OCI_RUNTIME") or os.environ.get("CONTAINER"):
        return True

    return False


def _detect_termux() -> bool:
    """Return True if running in Termux on Android."""
    return bool(os.environ.get("TERMUX_VERSION"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect() -> OSInfo:
    """Detect and return the current operating-system environment.

    This function is idempotent and has no side effects.  It performs a
    small number of lightweight reads and subprocess calls (all with
    short timeouts) and returns an immutable :class:`OSInfo`.
    """
    system = _detect_system()
    os_rel = _os_release()
    distribution = _detect_distribution(system, os_rel)
    version = _detect_version(os_rel, distribution)
    arch = _detect_arch()
    package_manager = _detect_package_manager(system, distribution)
    shell = _detect_shell()
    is_root = _detect_root()
    is_wsl = _detect_wsl() if system == "Linux" else False
    is_docker = _detect_docker() if system == "Linux" else False
    is_termux = _detect_termux()

    return OSInfo(
        system=system,
        distribution=distribution,
        version=version,
        arch=arch,
        package_manager=package_manager,
        shell=shell,
        is_root=is_root,
        is_wsl=is_wsl,
        is_docker=is_docker,
        is_termux=is_termux,
    )
