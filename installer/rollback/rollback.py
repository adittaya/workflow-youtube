import json
import shutil
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from installer.logging.logger import get_logger

log = get_logger("rollback")

class RollbackManager:
    def __init__(self, state_dir: Optional[str] = None):
        if state_dir is None:
            state_dir = str(Path.home() / ".config" / "vplink3" / "rollback")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._actions: list[dict] = []
        self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    def record(self, action: str, **kwargs):
        entry = {
            "action": action,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self._actions.append(entry)
        log.debug(f"Rollback record: {action} {kwargs}")

    def record_file_backup(self, path: str):
        src = Path(path)
        if not src.exists():
            self.record("create_file", path=path)
            return

        backup_dir = self.state_dir / self._session_id / "files"
        backup_dir.mkdir(parents=True, exist_ok=True)

        rel_path = src.relative_to(src.anchor) if src.is_absolute() else src
        backup_path = backup_dir / str(rel_path).replace("/", "_")
        shutil.copy2(str(src), str(backup_path))

        self.record("modify_file", path=path, backup=str(backup_path))

    def record_package_install(self, pkg_name: str):
        self.record("install_package", package=pkg_name)

    def record_env_change(self, key: str, value: str, profile: str):
        self.record("set_env", key=key, value=value, profile=profile)

    def rollback(self, session_id: Optional[str] = None) -> bool:
        sid = session_id or self._session_id
        log.info(f"Rolling back session {sid}")

        for entry in reversed(self._actions):
            action = entry["action"]
            try:
                if action == "modify_file" and entry.get("backup"):
                    backup = Path(entry["backup"])
                    if backup.exists():
                        shutil.copy2(str(backup), entry["path"])
                        log.info(f"Restored {entry['path']} from backup")

                elif action == "create_file":
                    path = Path(entry["path"])
                    if path.exists():
                        path.unlink()
                        log.info(f"Removed {entry['path']}")

                elif action == "install_package":
                    log.info(f"Package {entry['package']} should be removed manually")

                elif action == "set_env":
                    log.info(f"Environment {entry['key']} in {entry.get('profile', '?')} should be reverted manually")

            except Exception as e:
                log.error(f"Rollback failed for {action}: {e}")

        self._actions.clear()
        log.info("Rollback completed")
        return True

    def save(self):
        state_file = self.state_dir / f"{self._session_id}.json"
        with open(state_file, "w") as f:
            json.dump({"session": self._session_id, "actions": self._actions}, f, indent=2)

    def load_session(self, session_id: str) -> bool:
        state_file = self.state_dir / f"{session_id}.json"
        if not state_file.exists():
            return False
        with open(state_file) as f:
            data = json.load(f)
        self._session_id = data["session"]
        self._actions = data["actions"]
        return True

    def list_sessions(self) -> list[str]:
        return sorted([f.stem for f in self.state_dir.glob("*.json")])
