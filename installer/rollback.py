"""Rollback support: an undo journal for install actions.

Every mutating action the installer performs records an undo step here. If a
stage fails, ``rollback()`` replays the steps in reverse order so the system is
left as close to its pre-install state as possible. Undo steps that cannot
safely run are logged, never guessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from installer.core import utils


class RollbackJournal:
    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self._steps: List[Dict] = []
        self._loaded = False

    # -- recording ---------------------------------------------------------
    def record_command(self, undo_argv: List[str], description: str) -> None:
        """Record a shell command that undoes a previous action."""
        self._steps.append({"type": "command", "argv": undo_argv,
                            "description": description})

    def record_remove(self, path: Path, description: str) -> None:
        """Record a path to delete (created file/dir)."""
        self._steps.append({"type": "remove", "path": str(path),
                            "description": description})

    def record_restore(self, path: Path, snapshot: str, description: str) -> None:
        """Record a previous file content to restore on rollback."""
        self._steps.append({"type": "restore", "path": str(path),
                            "snapshot": snapshot, "description": description})

    # -- replay ------------------------------------------------------------
    def rollback(self, log=None, run_undo=True) -> List[str]:
        """Replay undo steps in reverse. Returns descriptions of what was run.

        The journal is cleared after a successful rollback. Failed undo steps
        are returned as messages but never abort the loop.
        """
        executed: List[str] = []
        errors: List[str] = []
        for step in reversed(self._steps):
            kind = step["type"]
            desc = step["description"]
            try:
                if kind == "command":
                    if run_undo:
                        utils.run(step["argv"], check=True, timeout=600)
                    executed.append(f"reverted: {desc}")
                elif kind == "remove":
                    utils.remove_path(Path(step["path"]))
                    executed.append(f"removed {step['path']}")
                elif kind == "restore":
                    utils.atomic_write(Path(step["path"]), step["snapshot"])
                    executed.append(f"restored {step['path']}")
            except Exception as exc:  # noqa: BLE001 - undo must not kill the loop
                errors.append(f"undo failed for {desc}: {exc}")
        self._steps.clear()
        self.persist()
        for err in errors:
            if log:
                log.warn(err)
        return executed + errors

    # -- persistence -------------------------------------------------------
    def persist(self) -> None:
        if not self.path:
            return
        utils.write_json(self.path, {"steps": self._steps}, mode=0o600)

    def load(self) -> "RollbackJournal":
        if self._loaded:
            return self
        if self.path and self.path.exists():
            data = utils.read_json(self.path, {})
            self._steps = data.get("steps", [])
        self._loaded = True
        return self

    def clear(self) -> None:
        self._steps.clear()
        self.persist()

    def __len__(self) -> int:
        return len(self._steps)
