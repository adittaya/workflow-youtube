"""
Rollback and error recovery module.
Provides checkpoint-based rollback for failed operations.
"""
import shutil
from pathlib import Path
from typing import Callable, Optional

from installer import logging as log


class RollbackManager:
    """Manages rollback checkpoints. Each checkpoint can undo changes if subsequent steps fail."""

    def __init__(self):
        self._checkpoints: list[dict] = []
        self._completed: list[str] = []

    def checkpoint(self, name: str, undo: Optional[Callable] = None):
        """Register a checkpoint. If undo is provided, it will be called on rollback."""
        self._checkpoints.append({"name": name, "undo": undo})
        self._completed.append(name)
        log.debug(f"Checkpoint: {name}")

    def commit(self, name: str):
        """Mark a checkpoint as committed (no rollback needed)."""
        self._completed.append(name)

    def rollback(self, to_step: Optional[str] = None):
        """Roll back to a specific step, or undo all if no step given."""
        targets = self._checkpoints[:]
        if to_step:
            idx = next((i for i, c in enumerate(targets)
                       if c["name"] == to_step), None)
            if idx is not None:
                targets = targets[idx:]

        for cp in reversed(targets):
            if cp["undo"]:
                try:
                    cp["undo"]()
                    log.info(f"Rolled back: {cp['name']}")
                except Exception as e:
                    log.warn(f"Rollback failed for {cp['name']}: {e}")


_rollback = RollbackManager()


def get_manager() -> RollbackManager:
    return _rollback


def checkpoint(name: str, undo: Optional[Callable] = None):
    _rollback.checkpoint(name, undo)


def commit(name: str):
    _rollback.commit(name)


def rollback(to_step: Optional[str] = None):
    _rollback.rollback(to_step)


class FileBackup:
    """Backup a file before modifying it, with restore capability."""

    def __init__(self):
        self._backups: dict[str, Path] = {}

    def backup(self, path: str) -> bool:
        """Backup a file before modification."""
        p = Path(path)
        if not p.exists():
            return False
        backup_path = p.with_suffix(p.suffix + ".bak")
        try:
            shutil.copy2(str(p), str(backup_path))
            self._backups[str(p)] = backup_path
            log.debug(f"Backed up: {path} → {backup_path}")
            return True
        except OSError as e:
            log.warn(f"Cannot backup {path}: {e}")
            return False

    def restore(self, path: str) -> bool:
        """Restore a file from backup."""
        p = Path(path)
        backup = self._backups.get(str(p))
        if not backup or not backup.exists():
            return False
        try:
            shutil.copy2(str(backup), str(p))
            log.info(f"Restored: {path} from backup")
            return True
        except OSError as e:
            log.warn(f"Cannot restore {path}: {e}")
            return False

    def clean(self, path: Optional[str] = None):
        """Remove backup files."""
        if path:
            backup = self._backups.get(path)
            if backup and backup.exists():
                backup.unlink()
        else:
            for bk in self._backups.values():
                if bk.exists():
                    bk.unlink()
