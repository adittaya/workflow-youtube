from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Optional

from installer.core.executor import check_command, run_command
from installer.platforms.base import BasePlatform, PlatformInfo


class WindowsPlatform(BasePlatform):

    @staticmethod
    def detect() -> PlatformInfo:
        version = platform.win32_ver()[0] or platform.release()

        machine = platform.machine().lower()
        ARCH_MAP = {
            "x86_64": "x86_64", "amd64": "x86_64",
            "aarch64": "aarch64", "arm64": "aarch64",
            "i686": "i686", "i386": "i686",
        }
        arch = ARCH_MAP.get(machine, machine)

        pkg_manager: str = "winget"
        for pm in ("winget", "choco", "scoop"):
            if check_command(pm):
                pkg_manager = pm
                break

        has_sudo = bool(os.environ.get("PSModulePath", False))

        home = os.path.expanduser("~")
        user = os.environ.get("USERNAME", os.environ.get("USER", "unknown"))

        shell = "powershell" if os.environ.get("PSModulePath") else "cmd"

        shell_profile = os.path.join(
            home, "Documents", "WindowsPowerShell",
            "Microsoft.PowerShell_profile.ps1",
        ) if shell == "powershell" else os.path.join(home, ".profile")

        appdata = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        roamdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))

        return PlatformInfo(
            name="windows",
            distribution="windows",
            version=version,
            arch=arch,
            package_manager=pkg_manager,
            has_sudo=has_sudo,
            is_wsl=False,
            is_docker=False,
            config_dir=os.path.join(roamdata, "vplink3"),
            data_dir=os.path.join(appdata, "vplink3"),
            cache_dir=os.path.join(appdata, "vplink3", "cache"),
            shell=shell,
            shell_profile=shell_profile,
            home=home,
            user=user,
        )

    @staticmethod
    def install_package(pkg_name: str, sudo: bool = True) -> bool:
        pm = WindowsPlatform.detect().package_manager
        if pm == "winget":
            cmd = f'winget install --id {pkg_name}'
        elif pm == "choco":
            cmd = f"choco install -y {pkg_name}"
        elif pm == "scoop":
            cmd = f'scoop install {pkg_name}'
        else:
            return False
        result = run_command(cmd, timeout=300)
        return result.success

    @staticmethod
    def update_package_index(sudo: bool = True) -> bool:
        pm = WindowsPlatform.detect().package_manager
        cmd_map = {
            "winget": "winget source update",
            "choco": "choco upgrade chocolatey -y",
            "scoop": "scoop update",
        }
        cmd = cmd_map.get(pm)
        if not cmd:
            return False
        result = run_command(cmd, timeout=120)
        return result.success

    @staticmethod
    def package_available(pkg_name: str) -> bool:
        pm = WindowsPlatform.detect().package_manager
        if pm == "winget":
            cmd = f'winget search {pkg_name}'
        elif pm == "choco":
            cmd = f"choco search {pkg_name}"
        elif pm == "scoop":
            cmd = f"scoop search {pkg_name}"
        else:
            return False
        result = run_command(cmd, timeout=60)
        return result.success

    @staticmethod
    def get_package_version(pkg_name: str) -> Optional[str]:
        return None
