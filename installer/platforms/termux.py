"""
Termux (Android) platform implementation.
"""
import subprocess
from installer.platforms.base import BasePlatform, InstallResult
from installer.packages import get_package, is_installed


class TermuxPlatform(BasePlatform):
    def install_package(self, name: str) -> InstallResult:
        installed, version = is_installed(name)
        if installed:
            return InstallResult(True, name, version)

        pkg = get_package(name)
        if not pkg:
            return InstallResult(False, name, error=f"Unknown package: {name}")

        cmd = pkg.termux.get("install", f"pkg install -y {name}")

        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
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
        try:
            subprocess.run("pkg update -y", shell=True, capture_output=True, timeout=120)
            return True
        except Exception:
            return False

    def system_info(self) -> dict:
        return {
            "os": "Termux/Android",
            "arch": self.info.arch,
            "shell": self.info.shell,
            "package_manager": "pkg",
        }
