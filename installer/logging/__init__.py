"""
Logging module for the installer.
Provides structured logging with levels, file output, and console display.
"""
import datetime
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Optional


LOG_LEVELS = {"debug": 0, "info": 1, "warn": 2, "error": 3, "success": 1}

_log_file: Optional[Path] = None
_log_level: int = 0
_log_entries: list = []
_colors_enabled: bool = True


def init(log_dir: Optional[str] = None, level: str = "info", colors: bool = True):
    global _log_file, _log_level, _colors_enabled
    _colors_enabled = colors
    _log_level = LOG_LEVELS.get(level, 0)

    if log_dir:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_file = path / f"install_{ts}.log"


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _color_code(level: str) -> str:
    codes = {"debug": "\033[2m", "info": "\033[0m", "warn": "\033[33m",
             "error": "\033[31m", "success": "\033[32m", "header": "\033[36m\033[1m"}
    return codes.get(level, "\033[0m")


def _write(level: str, message: str, details: str = ""):
    global _log_entries
    ts = _timestamp()
    entry = {"ts": ts, "level": level, "msg": message, "details": details}
    _log_entries.append(entry)

    # Console output
    if _log_level <= LOG_LEVELS.get(level, 1):
        if level == "success":
            prefix = "✓"
        elif level == "error":
            prefix = "✗"
        elif level == "warn":
            prefix = "⚠"
        else:
            prefix = " "

        if _colors_enabled and sys.stdout.isatty():
            color = _color_code(level)
            reset = "\033[0m"
            print(f"  {color}{prefix} {message}{reset}")
        else:
            print(f"  {prefix} {message}")

    # File output
    if _log_file:
        try:
            with open(_log_file, "a") as f:
                f.write(f"[{ts}] [{level.upper()}] {message}\n")
                if details:
                    f.write(f"  {details}\n")
        except OSError:
            pass


def info(msg: str):
    _write("info", msg)


def success(msg: str):
    _write("success", msg)


def warn(msg: str):
    _write("warn", msg)


def error(msg: str):
    _write("error", msg)


def debug(msg: str):
    _write("debug", msg)


def header(msg: str):
    if _colors_enabled and sys.stdout.isatty():
        print(f"\n  \033[36m\033[1m{msg}\033[0m")
        print(f"  \033[2m{'─' * min(len(msg), 60)}\033[0m")
    else:
        print(f"\n  {msg}")
        print(f"  {'─' * min(len(msg), 60)}")


def divider():
    print(f"  \033[2m{'─' * 50}\033[0m" if _colors_enabled else f"  {'─' * 50}")


def summary():
    """Print summary of all log entries."""
    entries = _log_entries[:]
    errors = [e for e in entries if e["level"] == "error"]
    warnings = [e for e in entries if e["level"] == "warn"]
    successes = [e for e in entries if e["level"] == "success"]

    print()
    header("Summary")
    print(f"  {'✓':<4} {len(successes)} succeeded")
    if warnings:
        print(f"  {'⚠':<4} {len(warnings)} warnings")
    if errors:
        print(f"  {'✗':<4} {len(errors)} errors")
    print()

    if errors:
        error("The following errors occurred:")
        for e in errors:
            print(f"    • {e['msg']}")

    if _log_file:
        print(f"  Log file: {_log_file}")


def get_log_path() -> Optional[Path]:
    return _log_file


def get_entries() -> list:
    return _log_entries[:]


def export_json(path: str):
    """Export log as JSON."""
    with open(path, "w") as f:
        json.dump(_log_entries, f, indent=2)
