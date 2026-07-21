"""
Security utilities for the installer.
Safe shell execution, input validation, permission handling.
"""
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional


def safe_run(cmd: list[str], timeout: int = 120, check: bool = False,
             capture: bool = True) -> subprocess.CompletedProcess:
    """Safely run a command with a list of arguments (no shell injection)."""
    for arg in cmd:
        if not isinstance(arg, str):
            raise ValueError(f"Non-string argument: {arg}")
    try:
        return subprocess.run(
            cmd, capture_output=capture, text=True, timeout=timeout, check=check,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}") from e


def safe_run_shell(command: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a shell command safely (only use when shell features are needed)."""
    # Validate command doesn't contain dangerous patterns
    dangerous = ["rm -rf /", "mkfs.", "dd if=", "> /dev/", "chmod 777 /"]
    for d in dangerous:
        if d in command.lower():
            raise ValueError(f"Potentially dangerous command rejected: {d}")
    return subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)


def validate_input(value: str, pattern: str = r"^[a-zA-Z0-9_-]+$") -> bool:
    """Validate user input against a regex pattern (prevents injection)."""
    return bool(re.match(pattern, value))


def validate_url(url: str) -> bool:
    """Validate URL is safe."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and "." in parsed.netloc


def check_permissions(path: str, mode: int = os.W_OK) -> bool:
    """Check if we have the necessary permissions for a path."""
    try:
        return os.access(path, mode)
    except OSError:
        return False


def ensure_secure_path(path: str, mode: int = 0o700) -> Path:
    """Create directory with secure permissions (owner-only)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(mode)
    except OSError:
        pass
    return p


def is_safe_to_delete(path: str) -> bool:
    """Check if a path is safe to delete (not root, not system directories)."""
    p = Path(path).resolve()
    unsafe_prefixes = ["/", "/etc", "/bin", "/sbin", "/usr", "/boot", "/dev",
                       "/proc", "/sys", "/lib", "/lib64", "/opt", "/var"]
    for prefix in unsafe_prefixes:
        if str(p) == prefix or str(p).startswith(prefix + "/"):
            return False
    return True


def sanitize_filename(name: str) -> str:
    """Remove dangerous characters from filenames."""
    return re.sub(r'[^\w\.\-\(\) ]', '', name)
