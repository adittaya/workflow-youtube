"""Install state machine: which stages ran, their outcome, and metadata.

State lives in the platform config directory (``~/.config/installer/state.json``
on POSIX). It lets ``installer status`` report progress, lets ``installer
install`` resume/skip already-completed stages, and lets ``installer repair``
detect incomplete installations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from installer.core import utils

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"


class InstallState:
    def __init__(self, path: Path, data: Optional[dict] = None):
        self.path = path
        self.data = data if data is not None else {"stages": {}, "meta": {}}

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def load(cls, base_dir: Path, filename: str = "state.json") -> "InstallState":
        path = Path(base_dir) / filename
        return cls(path, utils.read_json(path, {"stages": {}, "meta": {}}))

    def save(self) -> None:
        utils.write_json(self.path, self.data, mode=0o600)

    # -- stages ------------------------------------------------------------
    def begin_stage(self, name: str) -> None:
        self.data["stages"][name] = {
            "status": IN_PROGRESS,
            "started": self._now(),
        }

    def end_stage(self, name: str, status: str = DONE, detail: str = "") -> None:
        stage = self.data["stages"].setdefault(name, {})
        stage["status"] = status
        stage["ended"] = self._now()
        if detail:
            stage["detail"] = detail

    def stage_status(self, name: str) -> str:
        return self.data["stages"].get(name, {}).get("status", PENDING)

    def completed_stages(self) -> list:
        return [k for k, v in self.data["stages"].items() if v.get("status") == DONE]

    # -- metadata ----------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.data["meta"][key] = value

    def meta(self, key: str, default: Any = None) -> Any:
        return self.data["meta"].get(key, default)

    # -- queries -----------------------------------------------------------
    def is_installed(self) -> bool:
        """True when the full install ran to completion at least once."""
        return self.meta("installed") is True

    def needs_repair(self) -> list:
        return [k for k, v in self.data["stages"].items() if v.get("status") == FAILED]

    def mark_installed(self, version: str) -> None:
        self.set_meta("installed", True)
        self.set_meta("installed_at", self._now())
        self.set_meta("installed_version", version)

    def mark_uninstalled(self) -> None:
        self.set_meta("installed", False)
        self.set_meta("uninstalled_at", self._now())

    def to_dict(self) -> dict:
        return self.data

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
