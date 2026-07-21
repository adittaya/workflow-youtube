"""
Linux platform implementation.
Handles apt, dnf, pacman, zypper, apk, emerge, etc.
"""
import shutil
import subprocess
from installer.platforms.base import BasePlatform, InstallResult
from installer.core.platform import PlatformInfo, detect
from installer.packages import get_package, is_installed
from installer import logging as log


class LinuxPlatform(BasePlatform):
    def __init__(self, info: PlatformInfo):
        super().__init__(info)
        self._update_done = False

    def install_package(self, name: str) -> InstallResult:
        # Check if already installed
        installed, version = is_installed(name)
        if installed:
            return InstallResult(True, name, version)

        pkg = get_package(name)
        if not pkg:
            return InstallResult(False, name, error=f"Unknown package: {name}")

        pm = self.info.package_manager
        pkg_map = pkg.linux
        cmd_key = pm if pm in pkg_map else "apt"
        cmd = pkg_map.get(cmd_key) or pkg_map.get("apt")
        if not cmd:
            return InstallResult(False, name, error=f"No install command for {pm}")

        try:
            if pm == "apt":
                cmd_full = f"sudo {cmd}" if not self.info.is_root else cmd
            else:
                cmd_full = cmd if self.info.is_root else f"sudo {cmd}"

            result = subprocess.run(
                cmd_full, shell=True, capture_output=True, text=True, timeout=180
            )
            if result.returncode == 0:
                installed, version = is_installed(name)
                return InstallResult(True, name, version)
            else:
                return InstallResult(False, name, error=result.stderr[:500])
        except subprocess.TimeoutExpired:
            return InstallResult(False, name, error="Installation timed out")
        except Exception as e:
            return InstallResult(False, name, error=str(e))

    def install_packages(self, names: list[str]) -> list[InstallResult]:
        results = []
        for name in names:
            results.append(self.install_package(name))
        return results

    def update_package_db(self) -> bool:
        pm = self.info.package_manager
        cmd = ""
        if pm == "apt":
            cmd = "sudo apt update" if not self.info.is_root else "apt update"
        elif pm == "dnf":
            cmd = "sudo dnf check-update" if not self.info.is_root else "dnf check-update"
        elif pm == "pacman":
            cmd = "sudo pacman -Sy" if not self.info.is_root else "pacman -Sy"
        elif pm == "zypper":
            cmd = "sudo zypper refresh" if not self.info.is_root else "zypper refresh"
        elif pm == "apk":
            cmd = "apk update"

        if not cmd:
            return False

        try:
            subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            self._update_done = True
            return True
        except Exception:
            return False

    def system_info(self) -> dict:
        dist = self.info.distribution
        version = self.info.dist_version
        kernel = ""
        try:
            kernel = subprocess.run(["uname", "-r"], capture_output=True, text=True).stdout.strip()
        except Exception:
            pass
        return {
            "os": f"Linux/{dist}",
            "distribution": dist,
            "version": version,
            "kernel": kernel,
            "package_manager": self.info.package_manager,
            "arch": self.info.arch,
            "is_wsl": self.info.is_wsl,
            "is_docker": self.info.is_docker,
            "has_systemd": self.info.has_systemd,
        }
