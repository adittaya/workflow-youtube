from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Optional

from installer.core.executor import check_command, run_command
from installer.platforms.base import BasePlatform, PlatformInfo


class TermuxPlatform(BasePlatform):

    @staticmethod
    def detect() -> PlatformInfo:
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        version = os.environ.get("TERMUX_VERSION", platform.release())

        machine = platform.machine().lower()
        ARCH_MAP = {
            "aarch64": "aarch64", "arm64": "aarch64",
            "armv7l": "armv7l", "armv8l": "armv7l",
            "x86_64": "x86_64", "i686": "i686",
        }
        arch = ARCH_MAP.get(machine, machine)

        pkg_manager = "pkg"

        home = os.path.expanduser("~")
        user = os.environ.get("USER", os.environ.get("LOGNAME", "unknown"))

        # Termux uses bash by default
        shell = "bash"
        shell_profile = os.path.join(home, ".bashrc")

        config_home = os.environ.get(
            "VPLINK_CONFIG_DIR",
            os.path.join(home, ".config", "vplink3"),
        )

        return PlatformInfo(
            name="termux",
            distribution="termux",
            version=version,
            arch=arch,
            package_manager=pkg_manager,
            has_sudo=False,
            is_wsl=False,
            is_docker=False,
            config_dir=config_home,
            data_dir=os.path.join(prefix, "var", "lib", "vplink3"),
            cache_dir=os.path.join(prefix, "var", "cache", "vplink3"),
            shell=shell,
            shell_profile=shell_profile,
            home=home,
            user=user,
        )

    @staticmethod
    def install_package(pkg_name: str, sudo: bool = True) -> bool:
        cmd = f"pkg install -y {pkg_name}"
        result = run_command(cmd, timeout=300)
        return result.success

    @staticmethod
    def update_package_index(sudo: bool = True) -> bool:
        result = run_command("pkg update", timeout=120)
        return result.success

    @staticmethod
    def package_available(pkg_name: str) -> bool:
        cmd = f"pkg show {pkg_name}"
        result = run_command(cmd, timeout=30)
        return result.success

    @staticmethod
    def get_package_version(pkg_name: str) -> Optional[str]:
        cmd = f"dpkg -s {pkg_name}"
        result = run_command(cmd, timeout=10)
        if not result.success:
            return None
        match = re.search(r"^Version:\s*(\S+)", result.stdout, re.MULTILINE)
        if match:
            return match.group(1)
        return None
