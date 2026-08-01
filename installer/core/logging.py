"""Consistent logging to console and to a rotating log file.

Every log line written to the file is prefixed with a UTC timestamp and a level
so ``installer logs`` can be used for support and debugging. Console output is
coloured when the terminal supports it.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from installer.core import env

ANSI = {"reset": "\x1b[0m", "grey": "\x1b[90m", "red": "\x1b[31m",
        "green": "\x1b[32m", "yellow": "\x1b[33m", "cyan": "\x1b[36m",
        "bold": "\x1b[1m"}


def _color(supported: bool) -> dict:
    if not supported or os.environ.get("NO_COLOR"):
        return {k: "" for k in ANSI}
    return ANSI


class Logger:
    """Thread-safe logger writing to console and a single file."""

    def __init__(self, name: str, file_dir: Optional[Path] = None,
                 verbose: bool = False, console: bool = True):
        self.name = name
        self.verbose = verbose
        self.console = console
        self._lock = threading.Lock()
        self._file_path: Optional[Path] = None
        self._fh = None
        self.color = _color(hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
        if file_dir is not None:
            self.file_dir = file_dir
        elif name:
            self.file_dir = env.log_home(name)

    @property
    def file_dir(self) -> Optional[Path]:
        return self._file_dir

    @file_dir.setter
    def file_dir(self, value: Path):
        self._file_dir = Path(value)
        self._file_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self._file_dir / "installer.log"
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
        self._fh = open(self._file_path, "a", encoding="utf-8")

    # -- level helpers -----------------------------------------------------
    def debug(self, msg: str):
        if self.verbose:
            self._write("DEBUG", msg, "grey")

    def info(self, msg: str):
        self._write("INFO", msg, "cyan")

    def success(self, msg: str):
        self._write("OK", msg, "green")

    def warn(self, msg: str):
        self._write("WARN", msg, "yellow")

    def error(self, msg: str):
        self._write("ERROR", msg, "red")

    def step(self, msg: str):
        """Progress banner used for install stages (always shown)."""
        self._write("STEP", msg, "bold")

    def raw(self, msg: str = ""):
        if self.console:
            with self._lock:
                print(msg, flush=True)

    # -- core --------------------------------------------------------------
    def _write(self, level: str, msg: str, color_key: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            if self._fh:
                try:
                    self._fh.write(f"{ts} [{level}] {msg}\n")
                    self._fh.flush()
                except OSError:
                    pass
            if self.console:
                c = self.color.get(color_key, "")
                reset = self.color.get("reset", "")
                print(f"{c}{msg}{reset}", flush=True)

    def close(self):
        with self._lock:
            if self._fh:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None

    def log_file(self) -> Optional[Path]:
        return self._file_path

    @classmethod
    def tail(cls, file_path: Path, lines: int = 40) -> str:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        tail = content.splitlines()[-lines:]
        return "\n".join(tail)


# Module-level singleton so every module shares one sink.
_logger: Optional[Logger] = None
_lock = threading.Lock()


def get_logger() -> Logger:
    global _logger
    with _lock:
        if _logger is None:
            _logger = Logger("installer", verbose=False)
        return _logger


def configure_logger(file_dir: Optional[Path] = None, verbose: bool = False,
                     console: bool = True) -> Logger:
    global _logger
    with _lock:
        if _logger is None:
            _logger = Logger("installer", file_dir=file_dir, verbose=verbose,
                             console=console)
        else:
            if file_dir is not None:
                _logger.file_dir = file_dir
            _logger.verbose = verbose
            _logger.console = console
        return _logger
