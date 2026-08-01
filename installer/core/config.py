"""Configuration storage in platform-standard locations.

Supports JSON (default), YAML and TOML. YAML and TOML *reading* is done with a
small, dependency-free parser for the subset of syntax the installer itself
writes and that is commonly used for tool configuration (flat/nested mappings
of scalars, lists, and simple arrays). Writing always uses the requested
format. JSON is lossless and is the default.
"""

from __future__ import annotations

import json
import tomllib  # Python >= 3.11
from pathlib import Path
from typing import Any, Optional

from installer.core import env

SUPPORTED = ("json", "yaml", "toml")


# --------------------------------------------------------------------------
# Minimal YAML subset parser/writer
# --------------------------------------------------------------------------

def _parse_yaml_scalar(text: str) -> Any:
    t = text.strip()
    if t in ("null", "~", ""):
        return None
    if t in ("true", "True"):
        return True
    if t in ("false", "False"):
        return False
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        return t[1:-1]
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(x) for x in inner.split(",")]
    return t


def _load_yaml(text: str) -> dict:
    """Parse a small subset of YAML (indentation-based mappings and lists)."""
    data: dict = {}
    stack: list = [(-1, data)]
    for lineno, raw in enumerate(text.splitlines()):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"yaml indentation error at line {lineno + 1}")
        parent = stack[-1][1]
        if content.startswith("- "):
            item = _parse_yaml_scalar(content[2:])
            if isinstance(parent, list):
                parent.append(item)
            else:
                raise ValueError(f"unexpected list at line {lineno + 1}")
            continue
        if ":" not in content:
            raise ValueError(f"yaml parse error at line {lineno + 1}: {content}")
        key, _, value = content.partition(":")
        key = key.strip().strip("\"'")
        value = value.strip()
        if value in ("", "|", ">"):
            child: Any = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_yaml_scalar(value)
    return data


def _dump_yaml(data: dict, indent: int = 0) -> str:
    out: list[str] = []

    def scalar(v: Any) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return json.dumps(v)
        return str(v)

    def walk(node: Any, level: int):
        pad = "  " * level
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict):
                    out.append(f"{pad}{k}:")
                    walk(v, level + 1)
                elif isinstance(v, list):
                    out.append(f"{pad}{k}: [{', '.join(scalar(x) for x in v)}]")
                else:
                    out.append(f"{pad}{k}: {scalar(v)}")
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    out.append(f"{pad}-")
                    walk(item, level + 1)
                else:
                    out.append(f"{pad}- {scalar(item)}")

    walk(data, indent)
    return "\n".join(out)


# --------------------------------------------------------------------------
# TOML helpers (stdlib tomllib reads; small writer)
# --------------------------------------------------------------------------

def _load_toml(text: str) -> dict:
    return tomllib.loads(text)


def _dump_toml(data: dict) -> str:
    lines: list[str] = []

    def scalar(v: Any) -> str:
        if v is None:
            return '""'
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return json.dumps(v)
        if isinstance(v, list):
            return "[" + ", ".join(scalar(x) for x in v) + "]"
        return json.dumps(str(v))

    for k, v in data.items():
        if isinstance(v, dict):
            lines.append(f"[{k}]")
            for kk, vv in v.items():
                lines.append(f"{kk} = {scalar(vv)}")
        else:
            lines.append(f"{k} = {scalar(v)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Config store
# --------------------------------------------------------------------------

class ConfigError(RuntimeError):
    pass


class Config:
    """A dict-like config with a fixed platform-standard location."""

    def __init__(self, data: Optional[dict] = None):
        self.data: dict = data if data is not None else {}

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def section(self, key: str) -> "Config":
        sub = self.data.setdefault(key, {})
        if not isinstance(sub, dict):
            sub = {}
            self.data[key] = sub
        return Config(sub)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def to_dict(self) -> dict:
        return self.data

    def merged(self, other: dict) -> dict:
        merged = dict(self.data)
        for k, v in other.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        return merged


class ConfigStore:
    """Read/write a single config file in a platform-standard directory."""

    def __init__(self, app: str, filename: str = "config.json", fmt: str = "json",
                 base_dir: Optional[Path] = None):
        if fmt not in SUPPORTED:
            raise ConfigError(f"unsupported config format: {fmt}")
        self.app = app
        self.fmt = fmt
        self.base_dir = Path(base_dir) if base_dir else env.config_home(app)
        self.path = self.base_dir / filename

    # -- loaders -----------------------------------------------------------
    def load(self) -> Config:
        if not self.path.exists():
            return Config()
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read {self.path}: {exc}")
        try:
            fmt = self._detect(text)
            if fmt == "json":
                data = json.loads(text)
            elif fmt == "yaml":
                data = _load_yaml(text)
            else:
                data = _load_toml(text)
        except Exception as exc:
            raise ConfigError(f"cannot parse {self.path} ({self.fmt}): {exc}")
        if not isinstance(data, dict):
            raise ConfigError(f"config root must be a mapping: {self.path}")
        return Config(data)

    def save(self, config: Config) -> None:
        text = self._dump(config.to_dict())
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            from installer.core import utils

            utils.atomic_write(self.path, text, mode=0o600)
        except OSError as exc:
            raise ConfigError(f"cannot write {self.path}: {exc}")

    def _dump(self, data: dict) -> str:
        if self.fmt == "json":
            return json.dumps(data, indent=2, sort_keys=True) + "\n"
        if self.fmt == "yaml":
            return _dump_yaml(data) + "\n"
        return _dump_toml(data) + "\n"

    @staticmethod
    def _detect(text: str) -> str:
        stripped = text.lstrip()
        if stripped.startswith("{"):
            return "json"
        if stripped.startswith("[") or stripped.startswith("## ") or " = " in text:
            return "toml"
        return "yaml"

    def exists(self) -> bool:
        return self.path.exists()


def load(app: str = "installer", filename: str = "config.json", fmt: str = "json",
         base_dir: Optional[Path] = None) -> Config:
    return ConfigStore(app, filename, fmt, base_dir).load()


def save(config: Config, app: str = "installer", filename: str = "config.json",
         fmt: str = "json", base_dir: Optional[Path] = None) -> None:
    ConfigStore(app, filename, fmt, base_dir).save(config)
