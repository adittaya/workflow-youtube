"""
Platform-specific implementations.
"""
from dataclasses import dataclass
from installer.platforms.linux import LinuxPlatform
from installer.platforms.macos import MacOSPlatform
from installer.platforms.windows import WindowsPlatform
from installer.platforms.termux import TermuxPlatform

from installer.core.platform import PlatformInfo, detect
from installer.core.env import detect as env_detect


@dataclass
class PlatformMeta:
    """Unified platform metadata returned by detect_platform()."""
    name: str
    distribution: str
    version: str
    arch: str
    package_manager: str
    shell: str
    is_root: bool
    is_wsl: bool
    is_docker: bool
    home: str
    config_dir: str
    data_dir: str
    bin_dir: str
    user: str = ""
    node: str = ""


def detect_platform() -> PlatformMeta:
    pi = detect()
    meta = PlatformMeta(
        name="macos" if pi.os_name == "darwin" else pi.os_name,
        distribution=pi.distribution or "",
        version=pi.dist_version or "",
        arch=pi.arch,
        package_manager=pi.package_manager,
        shell=pi.shell,
        is_root=pi.is_root,
        is_wsl=pi.is_wsl,
        is_docker=pi.is_docker,
        home=pi.home,
        config_dir=pi.config_dir,
        data_dir=pi.data_dir,
        bin_dir=pi.bin_dir,
    )
    import getpass, platform
    meta.user = getpass.getuser()
    meta.node = platform.node()
    return meta


def get_platform(info: PlatformInfo):
    if info.os_name == "termux":
        return TermuxPlatform(info)
    if info.os_name == "darwin":
        return MacOSPlatform(info)
    if info.os_name == "windows":
        return WindowsPlatform(info)
    return LinuxPlatform(info)
