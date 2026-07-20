from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlatformInfo:
    name: str  # linux, macos, windows, termux
    distribution: str  # ubuntu, debian, fedora, arch, opensuse, macos, windows, termux
    version: str
    arch: str  # x86_64, aarch64, armv7l
    package_manager: str  # apt, dnf, pacman, zypper, brew, winget, pkg
    has_sudo: bool
    is_wsl: bool
    is_docker: bool
    config_dir: str
    data_dir: str
    cache_dir: str
    shell: str  # bash, zsh, fish, powershell
    shell_profile: str  # path to shell profile
    home: str  # user home directory
    user: str  # current username


class BasePlatform:
    """Base class for platform-specific operations."""

    @staticmethod
    def detect() -> PlatformInfo:
        raise NotImplementedError

    @staticmethod
    def install_package(pkg_name: str, sudo: bool = True) -> bool:
        raise NotImplementedError

    @staticmethod
    def update_package_index(sudo: bool = True) -> bool:
        raise NotImplementedError

    @staticmethod
    def package_available(pkg_name: str) -> bool:
        """Check if a package exists in the repository."""
        raise NotImplementedError

    @staticmethod
    def get_package_version(pkg_name: str) -> Optional[str]:
        raise NotImplementedError
