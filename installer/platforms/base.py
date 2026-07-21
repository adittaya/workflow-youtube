"""
Base platform class.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from installer.core.platform import PlatformInfo


@dataclass
class InstallResult:
    success: bool
    package: str
    version: Optional[str] = None
    error: Optional[str] = None


class BasePlatform(ABC):
    def __init__(self, info: PlatformInfo):
        self.info = info

    @abstractmethod
    def install_package(self, name: str) -> InstallResult:
        ...

    @abstractmethod
    def install_packages(self, names: list[str]) -> list[InstallResult]:
        ...

    @abstractmethod
    def update_package_db(self) -> bool:
        ...

    @abstractmethod
    def system_info(self) -> dict:
        ...

    def is_installed(self, binary: str) -> bool:
        import shutil
        return shutil.which(binary) is not None
