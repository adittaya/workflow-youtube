from typing import Optional
import os
from installer.packages.definitions import PackageDef, PACKAGES
from installer.platforms import get_platform, PlatformInfo
from installer.logging.logger import get_logger
from installer.interactive.ui import status

log = get_logger("packages")

class PackageManager:
    def __init__(self):
        self.platform = get_platform()
        self.info = get_platform().detect() if hasattr(get_platform(), 'detect') else get_platform().detect()

    def get_pm_name(self, pkg: PackageDef) -> str:
        """Get the package manager name for this package on current platform."""
        mapping = {
            "apt": pkg.apt,
            "dnf": pkg.dnf,
            "pacman": pkg.pacman,
            "zypper": pkg.zypper,
            "brew": pkg.brew,
            "winget": pkg.winget,
            "chocolatey": pkg.chocolatey,
            "scoop": pkg.scoop,
            "pkg": pkg.pkg,
        }
        pm = self.info.package_manager
        name = mapping.get(pm, "")
        # Fallback chain for windows
        if not name and self.info.name == "windows":
            name = mapping.get("chocolatey") or mapping.get("scoop") or ""
        return name

    def install(self, pkg: PackageDef, use_sudo=True) -> bool:
        """Install a single package. Returns True if successful or already installed."""
        if self.is_installed(pkg):
            log.info(f"{pkg.display_name} already installed")
            return True

        pm_name = self.get_pm_name(pkg)
        if pm_name:
            status(f"Installing {pkg.display_name}")
            log.info(f"Installing {pkg.name} via {self.info.package_manager}: {pm_name}")
            result = get_platform().install_package(pm_name, use_sudo)
            if result:
                status(f"Installed {pkg.display_name}", "ok")
                log.info(f"{pkg.name} installed successfully")
                return True
            else:
                status(f"Failed to install {pkg.display_name} via package manager", "error")
                log.warning(f"{pkg.name} failed via package manager")

        # Try download fallback if available
        if pkg.download_url:
            status(f"Downloading {pkg.display_name}...")
            from installer.downloads.fetcher import download_file
            success = download_file(pkg.download_url, pkg.download_filename, pkg.sha256)
            if success:
                log.info(f"{pkg.name} downloaded successfully")
                return True

        return False

    def install_chromium_with_fallback(self, use_sudo=True) -> bool:
        """Install Chromium browser; fall back to Google Chrome if apt gives a snap wrapper."""
        from installer.packages.definitions import get_package
        from installer.platforms.linux import LinuxPlatform

        def _is_native(path: str) -> bool:
            try:
                with open(path, "rb") as f:
                    return f.read(4) == b"\x7fELF"
            except OSError:
                return False

        # Try normal chromium-browser installation
        chrom_pkg = get_package("chromium-browser")
        if chrom_pkg and not self.is_installed(chrom_pkg):
            pm_name = self.get_pm_name(chrom_pkg)
            if pm_name:
                status(f"Installing {chrom_pkg.display_name}")
                get_platform().install_package(pm_name, use_sudo)

        # Check if binary is a native ELF (not snap wrapper)
        native = _is_native("/usr/bin/chromium-browser") or _is_native("/usr/bin/chromium")
        if native:
            log.info("Chromium is a native binary")
            return True

        # Snap wrapper detected — install Google Chrome instead
        status("chromium-browser is a snap wrapper (incompatible with Cloud Shell/Docker)", "warn")
        status("Installing Google Chrome as fallback...")
        plat_cls = get_platform()
        if isinstance(plat_cls, LinuxPlatform):
            ok = plat_cls.install_google_chrome(use_sudo)
            if ok:
                status("Installing ChromeDriver for Google Chrome...")
                chromedriver_pkg = get_package("chromedriver")
                if chromedriver_pkg:
                    # chromedriver may also be snap-wrapped; remove it and let webdriver-manager handle it
                    if use_sudo:
                        os.system("sudo apt remove -y chromium-chromedriver 2>/dev/null")
                    else:
                        os.system("apt remove -y chromium-chromedriver 2>/dev/null")
                    os.system("pip3 install --quiet webdriver-manager 2>/dev/null")
                log.info("Google Chrome installed successfully")
                return True
            status("Google Chrome installation failed", "error")
            return False

        log.warning("Not on Linux — cannot install Google Chrome fallback")
        return False

    def is_installed(self, pkg: PackageDef) -> bool:
        """Check if a package is installed via binary check or PM."""
        from installer.core.executor import check_command

        if pkg.binary_check:
            found = check_command(pkg.binary_check)
            if found:
                log.debug(f"{pkg.name} found in PATH")
                return True

        return False

    def get_version(self, pkg: PackageDef) -> Optional[str]:
        """Get installed version of a package."""
        from installer.core.executor import run_command

        if pkg.binary_check and pkg.version_flag:
            result = run_command([pkg.binary_check, pkg.version_flag], capture=True)
            if result.success:
                version = result.stdout.strip().split("\n")[0]
                return version
        return None

    def install_many(self, packages: list[PackageDef], use_sudo=True) -> dict[str, bool]:
        """Install multiple packages. Returns dict of name→success."""
        results = {}
        for pkg in packages:
            results[pkg.name] = self.install(pkg, use_sudo)
        return results

    def install_all(self, use_sudo=True) -> dict[str, bool]:
        """Install all defined packages."""
        return self.install_many(PACKAGES, use_sudo)

    def install_category(self, category: str, use_sudo=True) -> dict[str, bool]:
        """Install all packages in a category."""
        from installer.packages.definitions import get_packages_by_category
        return self.install_many(get_packages_by_category(category), use_sudo)
