"""Environment detection: OS, distribution, architecture, shell, package
manager, privileges, WSL, Docker and existing dependencies.

Everything is pure detection — no side effects. All functions degrade
gracefully so the installer can run on a bare system.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path

from installer.core import utils


# --------------------------------------------------------------------------
# OS / platform identity
# --------------------------------------------------------------------------

def system() -> str:
    """Return a canonical platform string: linux | darwin | windows | termux."""
    if is_termux():
        return "termux"
    return platform.system().lower()


def is_linux() -> bool:
    return sys.platform.startswith("linux") and not is_termux()


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def is_termux() -> bool:
    return bool(os.environ.get("PREFIX")) and Path(os.environ["PREFIX"]).name == "usr"


def distro_id() -> str:
    """Linux distribution identifier (ubuntu, debian, fedora, arch, opensuse…)
    or '' when unknown."""
    if not is_linux():
        return ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("ID="):
                return line[3:].strip().strip("\"'")
    except OSError:
        pass
    return ""


def distro_like() -> str:
    """Space-separated ID_LIKE value from os-release (e.g. 'debian')."""
    if not is_linux():
        return ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("ID_LIKE="):
                return line[8:].strip().strip("\"'")
    except OSError:
        pass
    return ""


def architecture() -> str:
    """Normalised CPU architecture: x86_64 | aarch64 | arm64 | i386 | amd64."""
    machine = platform.machine().lower()
    mapping = {
        "amd64": "x86_64",
        "x86": "i386",
        "i686": "i386",
        "arm64": "aarch64",
    }
    return mapping.get(machine, machine)


def shell() -> str:
    """Detect the current interactive shell by name (bash, zsh, fish, pwsh,
    cmd, sh) or a sensible default for the platform."""
    if is_windows():
        if utils.which("pwsh") or utils.which("powershell"):
            return "pwsh"
        return "cmd"
    path = os.environ.get("SHELL", "")
    if path:
        return Path(path).name
    for candidate in ("bash", "zsh", "fish", "sh"):
        if utils.which(candidate):
            return candidate
    return "sh"


def package_manager() -> str:
    """Detect the primary package manager, or '' if none is obvious."""
    if is_termux():
        return "pkg"
    if is_windows():
        return "winget" if utils.which("winget") else ""
    if is_macos():
        return "brew" if utils.which("brew") else ""
    if is_linux():
        for pm in ("apt", "dnf", "pacman", "zypper"):
            if utils.which(pm):
                return pm
    return ""


# --------------------------------------------------------------------------
# Privileges
# --------------------------------------------------------------------------

def is_root() -> bool:
    """True when running with root (POSIX) privileges."""
    if is_windows():
        return False
    return os.geteuid() == 0  # type: ignore[attr-defined]


def is_admin() -> bool:
    """True for admin/root privileges on the current platform."""
    if is_windows():
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    return is_root()


# --------------------------------------------------------------------------
# Containers / virtualisation
# --------------------------------------------------------------------------

def is_wsl() -> bool:
    """Detect Windows Subsystem for Linux."""
    if not is_linux():
        return False
    if "WSL_INTEROP" in os.environ or "WSL_DISTRO_NAME" in os.environ:
        return True
    try:
        return bool(re.search(r"microsoft|wsl", platform.release(), re.I))
    except Exception:
        return False


def has_docker() -> Optional[str]:
    """Docker version string, or None when unavailable."""
    ver = utils.command_output(["docker", "--version"], "").strip()
    return ver or None


def docker_running() -> bool:
    """Best-effort check whether the Docker daemon is reachable."""
    return utils.run_ok(["docker", "info"], capture=True)


# --------------------------------------------------------------------------
# Existing software
# --------------------------------------------------------------------------

def version_of(program: str, arg: str = "--version") -> Optional[str]:
    """Return the first line of ``program <arg>`` output, or None."""
    return utils.command_output([program, arg], "").strip() or None


def existing_dependencies(names: Iterable[str]) -> dict:
    """Map each program name to its detected version (or None)."""
    out = {}
    for name in names:
        if name == "python":
            out[name] = python_version()
        elif name == "pip":
            out[name] = pip_version()
        else:
            out[name] = version_of(name)
    return out


def python_version() -> Optional[str]:
    return sys.version.split()[0] if sys.version else None


def python_meets_minimum() -> bool:
    from installer.version import MIN_PYTHON

    return sys.version_info[:2] >= MIN_PYTHON


def pip_version() -> Optional[str]:
    return version_of("pip3", "--version") or version_of("pip", "--version")


# --------------------------------------------------------------------------
# Standard directories
# --------------------------------------------------------------------------

def home_dir() -> Path:
    if is_windows():
        return Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
    return Path(os.path.expanduser("~"))


def config_home(app: str) -> Path:
    """Platform-standard config directory for ``app``."""
    if is_windows():
        base = Path(os.environ.get("APPDATA", home_dir() / "AppData" / "Roaming"))
        return base / app
    if is_macos():
        return home_dir() / "Library" / "Application Support" / app
    return Path(os.environ.get("XDG_CONFIG_HOME", home_dir() / ".config")) / app


def data_home(app: str) -> Path:
    """Platform-standard data directory for ``app`` (project source, logs)."""
    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", home_dir() / "AppData" / "Local"))
        return base / app
    if is_macos():
        return home_dir() / "Library" / "Application Support" / app
    return Path(os.environ.get("XDG_DATA_HOME", home_dir() / ".local" / "share")) / app


def log_home(app: str) -> Path:
    if is_windows():
        return data_home(app) / "logs"
    return config_home(app) / "logs"


def bin_dir() -> Path:
    """Where user-level executables are installed on this platform."""
    if is_windows():
        return home_dir() / ".local" / "bin"
    return home_dir() / ".local" / "bin"


def display_environment() -> dict:
    """A dict describing the environment, for logs and ``installer status``."""
    return {
        "system": system(),
        "distro": distro_id(),
        "distro_like": distro_like(),
        "architecture": architecture(),
        "shell": shell(),
        "package_manager": package_manager(),
        "wsl": is_wsl(),
        "docker": has_docker(),
        "python": python_version(),
        "pip": pip_version(),
        "root": is_root(),
        "admin": is_admin(),
        "hostname": platform.node(),
    }


def summary() -> str:
    parts = [f"OS: {system()}"]
    if distro_id():
        parts.append(distro_id())
    parts.append(f"arch {architecture()}")
    parts.append(f"shell {shell()}")
    if package_manager():
        parts.append(f"pkg {package_manager()}")
    if is_wsl():
        parts.append("wsl")
    if is_root():
        parts.append("root")
    return " | ".join(parts)
