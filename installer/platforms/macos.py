"""
macOS platform implementation.
"""
import subprocess
from installer.platforms.base import BasePlatform, InstallResult
from installer.packages import get_package, is_installed
from installer import logging as log


class MacOSPlatform(BasePlatform):
    def install_package(self, name: str) -> InstallResult:
        installed, version = is_installed(name)
        if installed:
            return InstallResult(True, name, version)

        pkg = get_package(name)
        if not pkg:
            return InstallResult(False, name, error=f"Unknown package: {name}")

        cmd = pkg.macos.get("install", f"brew install {name}")

        if not self._has_brew() and "brew" in cmd:
            self._install_brew()

        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                installed, version = is_installed(name)
                return InstallResult(True, name, version)
            return InstallResult(False, name, error=result.stderr[:500])
        except subprocess.TimeoutExpired:
            return InstallResult(False, name, error="Timed out")
        except Exception as e:
            return InstallResult(False, name, error=str(e))

    def install_packages(self, names: list[str]) -> list[InstallResult]:
        results = []
        for name in names:
            results.append(self.install_package(name))
        return results

    def update_package_db(self) -> bool:
        if self._has_brew():
            try:
                subprocess.run("brew update", shell=True, capture_output=True, text=True, timeout=120)
                return True
            except Exception:
                pass
        return False

    def system_info(self) -> dict:
        sw_vers = ""
        try:
            sw_vers = subprocess.run(["sw_vers", "-productVersion"],
                                     capture_output=True, text=True).stdout.strip()
        except Exception:
            pass
        return {
            "os": "macOS",
            "version": sw_vers,
            "arch": self.info.arch,
            "has_brew": self._has_brew(),
            "shell": self.info.shell,
        }

    def _has_brew(self) -> bool:
        import shutil
        return shutil.which("brew") is not None

    def _install_brew(self):
        log.info("Installing Homebrew...")
        try:
            cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            subprocess.run(cmd, shell=True, timeout=300)
            log.success("Homebrew installed")
        except Exception as e:
            log.warn(f"Homebrew install failed: {e}")
