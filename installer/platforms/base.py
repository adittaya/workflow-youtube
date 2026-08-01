"""Base class and interface for package-manager backends."""

from __future__ import annotations

import abc
from typing import List, Optional

from installer.core import env, utils

#: Package managers whose commands require root/admin privileges.
_PRIVILEGED = {"apt", "dnf", "pacman", "zypper"}


class PlatformInstaller(abc.ABC):
    """Abstract package manager wrapper.

    Subclasses implement the four primitive operations; higher layers (see
    ``installer.operations``) use ``install``/``remove`` with logical package
    names mapped through the package registry.
    """

    name: str = "base"

    def __init__(self, log=None):
        self.log = log
        self._sudo_ok: Optional[bool] = None

    # -- abstract ----------------------------------------------------------
    @abc.abstractmethod
    def install(self, packages: List[str], dry_run: bool = False) -> bool:
        """Install ``packages`` (concrete names). Return success."""

    @abc.abstractmethod
    def remove(self, packages: List[str], dry_run: bool = False) -> bool:
        """Remove ``packages`` (concrete names). Return success."""

    @abc.abstractmethod
    def update(self, dry_run: bool = False) -> bool:
        """Refresh package indexes. Return success."""

    # -- shared ------------------------------------------------------------
    @property
    def needs_privileges(self) -> bool:
        return self.name in _PRIVILEGED

    def _sudo(self) -> bool:
        """Whether we should and can prefix commands with ``sudo``."""
        if self.name not in _PRIVILEGED or env.is_root() or env.is_windows():
            return False
        if self._sudo_ok is None:
            self._sudo_ok = utils.which("sudo") is not None
            if self._sudo_ok and not utils.stdin_is_interactive():
                # Non-interactive: confirm sudo works without a password prompt.
                self._sudo_ok = utils.run_ok(["sudo", "-n", "true"], capture=True)
        return bool(self._sudo_ok)

    def _run(self, argv: List[str], **kwargs):
        if self._sudo():
            argv = ["sudo", "-n"] + argv
        if self.log:
            self.log.debug("$ " + " ".join(argv))
        return utils.run(argv, check=False, **kwargs)

    def error_hint(self, packages: List[str]) -> str:
        """Friendly fix suggestion printed when an install fails."""
        return f"Install the following manually: {' '.join(packages)}"
