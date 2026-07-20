import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

class InstallerLogger:
    _instance: Optional['InstallerLogger'] = None

    def __init__(self, log_dir: Optional[str] = None):
        if log_dir is None:
            log_dir = str(Path.home() / ".config" / "vplink3" / "logs")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # File handler
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file = self.log_dir / f"install-{timestamp}.log"

        self.logger = logging.getLogger("vplink3")
        self.logger.setLevel(logging.DEBUG)

        # File handler (detailed)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self.logger.addHandler(fh)

        # Keep track of the log file path
        self._log_file = log_file

        # Store instance for get_logger
        InstallerLogger._instance = self

    @property
    def log_file(self) -> Path:
        return self._log_file

    def get_logger(self, name: str = "") -> logging.Logger:
        """Get a child logger."""
        if name:
            return self.logger.getChild(name)
        return self.logger

# Module-level convenience
def get_logger(name: str = "") -> logging.Logger:
    """Get or create the installer logger."""
    if InstallerLogger._instance is None:
        InstallerLogger()
    return InstallerLogger._instance.get_logger(name)

def get_log_file() -> Optional[Path]:
    """Get current log file path."""
    if InstallerLogger._instance:
        return InstallerLogger._instance.log_file
    return None

def init_logging(log_dir: Optional[str] = None):
    """Initialize the logging system. Call once at startup."""
    InstallerLogger(log_dir=log_dir)
