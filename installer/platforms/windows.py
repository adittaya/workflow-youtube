"""
Windows platform implementation (PowerShell + Winget).
"""
import subprocess
from installer.platforms.base import BasePlatform, InstallResult
from installer.packages import get_package, is_installed
from installer import logging as log


class WindowsPlatform(BasePlatform):
    def install_package(self, name: str) -> InstallResult:
        installed, version = is_installed(name)
        if installed:
            return InstallResult(True, name, version)

        pkg = get_package(name)
        if not pkg:
            return InstallResult(False, name, error=f"Unknown package: {name}")

        cmd = pkg.windows.get("install", f"winget install {name}")
        if "winget" in cmd and not self._has_winget():
            return InstallResult(False, name, error="winget not available")

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                installed, version = is_installed(name)
                return InstallResult(True, name, version)
            return InstallResult(False, name, error=result.stderr[:500])
        except subprocess.TimeoutExpired:
            return InstallResult(False, name, error="Timed out")
        except Exception as e:
            return InstallResult(False, name, error=str(e))

    def install_packages(self, names: list[str]) -> list[InstallResult]:
        return [self.install_package(n) for n in names]

    def update_package_db(self) -> bool:
        if self._has_winget():
            try:
                subprocess.run("winget source update", shell=True,
                               capture_output=True, timeout=60)
                return True
            except Exception:
                pass
        return False

    def system_info(self) -> dict:
        ver = ""
        try:
            ver = subprocess.run(["cmd", "/c", "ver"], capture_output=True, text=True).stdout.strip()
        except Exception:
            pass
        return {
            "os": "Windows",
            "version": ver,
            "arch": self.info.arch,
            "has_winget": self._has_winget(),
            "shell": self.info.shell,
        }

    def _has_winget(self) -> bool:
        import shutil
        return shutil.which("winget") is not None
