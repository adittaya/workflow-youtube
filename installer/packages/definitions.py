from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PackageDef:
    name: str                    # canonical name
    display_name: str            # human-readable name
    category: str                # "system", "runtime", "browser", "tool"
    # Per-platform package names (what the PM calls it)
    apt: Optional[str] = None
    dnf: Optional[str] = None
    pacman: Optional[str] = None
    zypper: Optional[str] = None
    brew: Optional[str] = None
    winget: Optional[str] = None  # winget ID
    chocolatey: Optional[str] = None  # choco fallback
    scoop: Optional[str] = None  # scoop fallback
    pkg: Optional[str] = None    # Termux
    # Verification
    binary_check: Optional[str] = None  # command to check in PATH
    version_flag: Optional[str] = "--version"  # flag to get version
    min_version: Optional[str] = None  # minimum acceptable version
    # Download fallback
    download_url: Optional[str] = None
    download_filename: Optional[str] = None
    sha256: Optional[str] = None
    # Metadata
    critical: bool = True        # if True, installer fails when this is missing
    description: str = ""

PACKAGES: list[PackageDef] = [
    PackageDef(
        name="git",
        display_name="Git",
        category="tool",
        apt="git", dnf="git", pacman="git", zypper="git",
        brew="git", winget="Git.Git", chocolatey="git", scoop="git",
        pkg="git",
        binary_check="git", version_flag="--version",
        critical=True,
        description="Version control system",
    ),
    PackageDef(
        name="python3",
        display_name="Python 3",
        category="runtime",
        apt="python3", dnf="python3", pacman="python", zypper="python3",
        brew="python@3", winget="Python.Python.3", chocolatey="python", scoop="python",
        pkg="python",
        binary_check="python3", version_flag="--version",
        min_version="3.10",
        critical=True,
        description="Python 3 runtime",
    ),
    PackageDef(
        name="pip3",
        display_name="pip",
        category="runtime",
        apt="python3-pip", dnf="python3-pip", pacman="python-pip", zypper="python3-pip",
        brew="", winget="", chocolatey="", scoop="",
        pkg="python-pip",
        binary_check="pip3", version_flag="--version",
        critical=True,
        description="Python package installer",
    ),
    PackageDef(
        name="chromium-browser",
        display_name="Chromium Browser",
        category="browser",
        apt="chromium-browser", dnf="chromium", pacman="chromium", zypper="chromium",
        brew="chromium", winget="", chocolatey="", scoop="",
        pkg="chromium",
        binary_check="chromium-browser", version_flag="--version",
        min_version="120",
        critical=True,
        download_url="https://www.chromium.org/getting-involved/download-chromium",
        description="Chromium web browser for Selenium automation",
    ),
    PackageDef(
        name="chromedriver",
        display_name="ChromeDriver",
        category="browser",
        apt="chromium-chromedriver", dnf="chromium-chromedriver", pacman="chromedriver", zypper="chromedriver",
        brew="chromedriver", winget="", chocolatey="", scoop="",
        pkg="chromedriver",
        binary_check="chromedriver", version_flag="--version",
        critical=True,
        description="WebDriver for Chromium automation",
    ),
    PackageDef(
        name="xvfb",
        display_name="Xvfb",
        category="system",
        apt="xvfb", dnf="xorg-x11-server-Xvfb", pacman="xvfb", zypper="xorg-x11-server",
        brew="", winget="", chocolatey="", scoop="",
        pkg="",
        binary_check="Xvfb", version_flag="--version",
        critical=False,
        description="Virtual framebuffer for headless display",
    ),
    PackageDef(
        name="x11vnc",
        display_name="x11vnc",
        category="system",
        apt="x11vnc", dnf="x11vnc", pacman="x11vnc", zypper="x11vnc",
        brew="", winget="", chocolatey="", scoop="",
        pkg="",
        binary_check="x11vnc", version_flag="--version",
        critical=False,
        description="VNC server for remote desktop",
    ),
    PackageDef(
        name="curl",
        display_name="curl",
        category="tool",
        apt="curl", dnf="curl", pacman="curl", zypper="curl",
        brew="curl", winget="", chocolatey="curl", scoop="curl",
        pkg="curl",
        binary_check="curl", version_flag="--version",
        critical=True,
        description="URL transfer tool",
    ),
    PackageDef(
        name="wget",
        display_name="wget",
        category="tool",
        apt="wget", dnf="wget", pacman="wget", zypper="wget",
        brew="wget", winget="", chocolatey="wget", scoop="wget",
        pkg="wget",
        binary_check="wget", version_flag="--version",
        critical=False,
        description="Network downloader",
    ),
]

def get_package(name: str) -> Optional[PackageDef]:
    """Look up a package definition by canonical name."""
    for pkg in PACKAGES:
        if pkg.name == name:
            return pkg
    return None

def get_packages_by_category(category: str) -> list[PackageDef]:
    """Get all packages in a category."""
    return [pkg for pkg in PACKAGES if pkg.category == category]
