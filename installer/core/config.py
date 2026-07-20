"""Persistent installer configuration for VPLink 3.0.

Stores JSON configuration at a platform-appropriate location and provides
a simple key-value interface with automatic persistence.  Pure stdlib —
no external dependencies.
"""

from __future__ import annotations

import json
import platform
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_DEFAULT_APP_NAME = "vplink3"
_DEFAULT_FILE_NAME = "installer.json"

# Canonical default keys
DEFAULTS: dict[str, Any] = {
    "installed_packages": [],
    "install_timestamp": "",
    "version": "",
    "config_dir": "",
    "log_dir": "",
    "shell_profile_modified": False,
    "installation_id": "",
}


def _platform_config_dir(app_name: str) -> Path:
    """Return the platform-standard configuration directory.

    * Linux / macOS / Termux → ``~/.config/<app_name>``
    * Windows               → ``%APPDATA%\\<app_name>``
    """
    system = platform.system()

    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Preferences"
    else:
        # Linux, Termux, and other POSIX
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"

    return base / app_name


def _atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via a temporary file + rename.

    On POSIX this guarantees that concurrent readers never see a
    half-written file.  Falls back to a direct write if the rename
    fails across filesystems.
    """
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        try:
            os.replace(tmp, path)
        except OSError:
            # Cross-filesystem rename — fall back
            shutil.move(tmp, str(path))
    except BaseException:
        os.close(fd) if not os.get_inheritable(fd) else None  # noqa: E712
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# We need ``os`` for env‑var lookups and atomic file ops — but keep it
# to just these two uses.
import os  # noqa: E402


class InstallerConfig:
    """JSON-backed configuration store for the VPLink 3.0 installer.

    Usage::

        cfg = InstallerConfig()
        cfg.set("version", "3.0.0")
        val = cfg.get("version")
        cfg.save()  # usually automatic
    """

    def __init__(self, app_name: str = _DEFAULT_APP_NAME) -> None:
        self._app_name = app_name
        self._dir = _platform_config_dir(app_name)
        self._path = self._dir / _DEFAULT_FILE_NAME
        self._data: dict[str, Any] = {}
        self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        """Load config from disk, merging with DEFAULTS for missing keys."""
        self._data = dict(DEFAULTS)
        if self._path.exists():
            try:
                stored = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    self._data.update(stored)
            except (json.JSONDecodeError, OSError):
                # Corrupted file — keep defaults and overwrite on save
                pass

        # Ensure first-run defaults are populated
        if not self._data.get("installation_id"):
            self._data["installation_id"] = str(uuid.uuid4())
        if not self._data.get("install_timestamp"):
            self._data["install_timestamp"] = datetime.now(
                tz=timezone.utc
            ).isoformat()
        if not self._data.get("version"):
            from installer import __version__
            self._data["version"] = __version__
        if not self._data.get("config_dir"):
            self._data["config_dir"] = str(self._dir)
        if not self._data.get("log_dir"):
            self._data["log_dir"] = str(self._dir / "logs")

    def save(self) -> None:
        """Persist the current configuration to disk."""
        self._data["config_dir"] = str(self._dir)
        self._data["log_dir"] = str(self._dir / "logs")
        _atomic_write(self._path, json.dumps(self._data, indent=2, default=str))

    # -- public API -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, or *default* if absent."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set *key* to *value* and persist to disk."""
        self._data[key] = value
        self.save()

    def update(self, mapping: dict[str, Any]) -> None:
        """Bulk-update multiple keys and persist once."""
        self._data.update(mapping)
        self.save()

    def delete(self, key: str) -> None:
        """Remove *key* if present and persist."""
        self._data.pop(key, None)
        self.save()

    def keys(self) -> list[str]:
        """Return all config keys."""
        return list(self._data.keys())

    def items(self) -> list[tuple[str, Any]]:
        """Return all (key, value) pairs."""
        return list(self._data.items())

    def as_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the full config dict."""
        return dict(self._data)

    # -- paths ----------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Absolute path to the config JSON file."""
        return self._path

    @property
    def config_dir(self) -> Path:
        """Absolute path to the configuration directory."""
        return self._dir

    @property
    def log_dir(self) -> Path:
        """Absolute path to the log directory (created on access)."""
        d = self._dir / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def __repr__(self) -> str:
        return f"<InstallerConfig path={self._path}>"
