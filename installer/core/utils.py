"""Low-level helpers: command execution, filesystem utilities, input prompts.

Everything here is deliberately dependency-free so the installer can bootstrap
an environment that may not even have pip installed yet.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

CommandResult = subprocess.CompletedProcess


def which(program: str) -> Optional[str]:
    """Return the absolute path of ``program`` on PATH, or None."""
    return shutil.which(program)


def run(
    argv: Sequence[str],
    *,
    check: bool = False,
    capture: bool = False,
    env: Optional[dict] = None,
    cwd: Optional[str] = None,
    timeout: Optional[float] = 600,
) -> CommandResult:
    """Run a command.

    ``capture=True`` returns stdout+stderr on ``.stdout`` and does not leak to
    the console. ``check=True`` raises ``CalledProcessError`` on failure, which
    the caller should translate into a friendly error.
    """
    proc = subprocess.run(
        list(argv),
        check=check,
        capture_output=capture,
        text=True,
        env=env,
        cwd=cwd,
        timeout=timeout,
    )
    if capture:
        proc.stdout = (proc.stdout or "").strip()
        proc.stderr = (proc.stderr or "").strip()
    return proc


def run_ok(argv: Sequence[str], **kwargs) -> bool:
    """Run a command and return True only if it exited 0."""
    try:
        return run(argv, **kwargs).returncode == 0
    except (FileNotFoundError, OSError):
        return False


def command_output(argv: Sequence[str], default: str = "", **kwargs) -> str:
    """Return trimmed stdout of a command, or ``default`` on any failure."""
    try:
        res = run(argv, capture=True, **kwargs)
        if res.returncode == 0:
            return res.stdout or default
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    return default


def probe_version(argv: Sequence[str], timeout: float = 30) -> str:
    """Best-effort version probe: first line of output, or ``""``.

    Unlike ``command_output`` this accepts output on stderr as well as stdout
    (some builds print version info to stderr on a zero exit) and never leaks
    to the console. A non-zero exit still means no usable version line.
    """
    try:
        res = run(argv, capture=True, timeout=timeout)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""
    if res.returncode != 0:
        return ""
    return (res.stdout or "").strip() or (res.stderr or "").strip()


def stdin_is_interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def confirm(
    prompt: str,
    default: bool = True,
    *,
    yes_no: str = "Y/n" if True else "y/N",
) -> bool:
    """Prompt for a y/n confirmation. Never raises; non-interactive -> default."""
    suffix = " (Y/n): " if default else " (y/N): "
    if not stdin_is_interactive():
        return default
    try:
        answer = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not answer:
        return default
    return answer.startswith("y")


def ask(prompt: str, default: str = "") -> str:
    """Prompt for a free-form answer with an optional default."""
    if not stdin_is_interactive():
        return default
    suffix = f" [{default}]: " if default else ": "
    try:
        answer = input(prompt + suffix).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def remove_path(path: Path) -> None:
    """Remove a file or directory tree, ignoring missing paths."""
    if path.is_file() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    """Write text atomically (tempfile + rename) so readers never see a
    partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), prefix="." + path.name, delete=False
    ) as fh:
        fh.write(text)
        tmp = fh.name
    try:
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default if default is not None else {}


def write_json(path: Path, data, mode: int = 0o600) -> None:
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n", mode=mode)


def format_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def is_url(value: str) -> bool:
    """Cheap, safe URL validation (https/http only)."""
    return value.startswith(("https://", "http://"))


def safe_shell_join(argv: Sequence[str]) -> str:
    """Join argv into a shell-quoted string (only for display/logging)."""
    return " ".join(shlex.quote(a) for a in argv)
