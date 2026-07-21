"""
Configuration module for the installer.
Manages config in platform-standard locations, supports JSON, YAML, TOML.
"""
import json
import os
from pathlib import Path
from typing import Any, Optional

from installer.core.platform import PlatformInfo, detect


def config_dir(info: Optional[PlatformInfo] = None) -> Path:
    if not info:
        info = detect()
    return Path(info.config_dir)


def data_dir(info: Optional[PlatformInfo] = None) -> Path:
    if not info:
        info = detect()
    return Path(info.data_dir)


def ensure_dirs(info: Optional[PlatformInfo] = None):
    info = info or detect()
    Path(info.config_dir).mkdir(parents=True, exist_ok=True)
    Path(info.data_dir).mkdir(parents=True, exist_ok=True)
    Path(info.bin_dir).mkdir(parents=True, exist_ok=True)


def load(path: str, fmt: str = "json") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    raw = p.read_text()
    if fmt == "json":
        return json.loads(raw)
    if fmt == "yaml":
        try:
            import yaml
            return yaml.safe_load(raw) or {}
        except ImportError:
            return {}
    if fmt == "toml":
        try:
            import tomllib
            return tomllib.loads(raw)
        except ImportError:
            try:
                import toml
                return toml.loads(raw)
            except ImportError:
                return {}
    return {}


def save(path: str, data: dict, fmt: str = "json"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        p.write_text(json.dumps(data, indent=2))
    elif fmt == "yaml":
        try:
            import yaml
            p.write_text(yaml.dump(data, default_flow_style=False))
        except ImportError:
            p.write_text(json.dumps(data, indent=2))
    elif fmt == "toml":
        try:
            import toml
            p.write_text(toml.dumps(data))
        except ImportError:
            p.write_text(json.dumps(data, indent=2))


class Config:
    def __init__(self, app_name: str = "vplink", info: Optional[PlatformInfo] = None):
        self.info = info or detect()
        self.base_dir = Path(self.info.config_dir) / app_name
        self.config_file = self.base_dir / "config.json"
        self._data: dict = {}

    def load(self) -> dict:
        if self.config_file.exists():
            try:
                self._data = json.loads(self.config_file.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        return self._data

    def save(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(self._data, indent=2))

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self.save()

    def delete(self, key: str):
        self._data.pop(key, None)
        self.save()

    def all(self) -> dict:
        return self._data.copy()

    def path(self) -> Path:
        return self.config_file
