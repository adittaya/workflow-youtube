from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Optional

from installer.core.executor import check_command, run_command
from installer.platforms.base import BasePlatform, PlatformInfo


class MacOSPlatform(BasePlatform):

    @staticmethod
    def detect() -> PlatformInfo:
        version = platform.mac_ver()[0] or platform.release()

        machine = platform.machine().lower()
        ARCH_MAP = {
            "x86_64": "x86_64", "amd64": "x86_64",
            "aarch64": "aarch64", "arm64": "aarch64",
        }
        arch = ARCH_MAP.get(machine, machine)

        pkg_manager = "brew" if check_command("brew") else "unknown"

        has_sudo = check_command("sudo")

        shell_path = os.environ.get("SHELL", "")
        shell = Path(shell_path).stem.lower() if shell_path else "zsh"

        home = os.path.expanduser("~")
        user = os.environ.get("USER", os.environ.get("LOGNAME", "unknown"))

        profile_map: dict[str, str] = {
            "bash": ".bash_profile",
            "zsh": ".zshrc",
            "fish": ".config/fish/config.fish",
            "sh": ".profile",
        }
        shell_profile = os.path.join(home, profile_map.get(shell, ".zshrc"))

        return PlatformInfo(
            name="macos",
            distribution="macos",
            version=version,
            arch=arch,
            package_manager=pkg_manager,
            has_sudo=has_sudo,
            is_wsl=False,
            is_docker=False,
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
        cmd = f"brew install {pkg_name}"
        result = run_command(cmd, timeout=300)
        return result.success

    @staticmethod
    def update_package_index(sudo: bool = True) -> bool:
        result = run_command("brew update", timeout=120)
        return result.success

    @staticmethod
    def package_available(pkg_name: str) -> bool:
        cmd = f"brew info {pkg_name}"
        result = run_command(cmd, timeout=30)
        return result.success and bool(result.stdout.strip())

    @staticmethod
    def get_package_version(pkg_name: str) -> Optional[str]:
        cmd = f"brew info --json=v1 {pkg_name}"
        result = run_command(cmd, timeout=30)
        if not result.success:
            return None
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("versions", {}).get("stable")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
        return None
