"""Safe command execution utilities for the VPLink 3.0 installer.

Wraps :mod:`subprocess` with logging, timeouts, structured results, and
a convenience layer for privilege escalation.  Pure stdlib — no
external dependencies.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger("vplink3.executor")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    """Structured result of a command execution."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    command: str = ""

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL(rc={self.exit_code})"
        cmd_short = self.command[:60] + "…" if len(self.command) > 60 else self.command
        return f"<CommandResult {status} {self.duration:.2f}s cmd={cmd_short!r}>"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CommandError(RuntimeError):
    """Raised when :func:`run_command` is called with ``check=True`` and
    the command exits with a non-zero status."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        parts = [
            f"Command failed (exit {result.exit_code}): {result.command}",
        ]
        if result.stderr:
            stderr_preview = result.stderr[:500].rstrip()
            parts.append(f"stderr: {stderr_preview}")
        super().__init__("\n".join(parts))


class CommandTimeout(RuntimeError):
    """Raised when a command exceeds its timeout."""

    def __init__(self, command: str, timeout: float) -> None:
        self.command = command
        self.timeout = timeout
        super().__init__(f"Command timed out after {timeout}s: {command}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_command(cmd: Union[str, List[str], Sequence[str]]) -> List[str]:
    """Ensure *cmd* is a list suitable for :func:`subprocess.run`.

    A plain string is split using POSIX shell rules (respects quotes).
    """
    if isinstance(cmd, str):
        return shlex.split(cmd)
    return list(cmd)


def _command_str(cmd: Union[str, List[str], Sequence[str]]) -> str:
    """Return a human-readable representation of *cmd*."""
    if isinstance(cmd, str):
        return cmd
    return shlex.join(cmd)


def _merge_env(env: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Return *env* merged on top of the current environment, or ``None``
    to inherit the parent environment entirely."""
    if env is None:
        return None
    base = dict(os.environ)
    base.update(env)
    return base


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

def run_command(
    cmd: Union[str, List[str], Sequence[str]],
    *,
    timeout: float = 120,
    check: bool = False,
    capture: bool = True,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> CommandResult:
    """Execute *cmd* and return a :class:`CommandResult`.

    Parameters
    ----------
    cmd:
        Command as a string (shell-split) or list of arguments.
    timeout:
        Maximum wall-clock seconds before the process is killed.
    check:
        If ``True``, raise :class:`CommandError` on non-zero exit.
    capture:
        If ``True``, capture stdout and stderr.  Set to ``False`` when
        you want live terminal output (e.g. interactive installers).
    cwd:
        Working directory for the subprocess.
    env:
        Extra environment variables merged on top of the inherited env.

    Returns
    -------
    CommandResult
        A structured result with stdout, stderr, exit code, and duration.
    """
    args = _coerce_command(cmd)
    cmd_display = _command_str(cmd)

    logger.debug("exec: %s (timeout=%.0fs, cwd=%s)", cmd_display, timeout, cwd)

    merged_env = _merge_env(env)
    t0 = time.monotonic()

    try:
        proc = subprocess.run(
            args,
            capture_output=capture,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=merged_env,
        )
        duration = time.monotonic() - t0

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
        success = exit_code == 0

        result = CommandResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration=duration,
            command=cmd_display,
        )

        if success:
            logger.debug("exec ok: %s (%.2fs)", cmd_display, duration)
        else:
            logger.warning(
                "exec fail rc=%d: %s (%.2fs) stderr=%s",
                exit_code, cmd_display, duration, stderr[:200],
            )

    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - t0
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else ""

        logger.error("exec timeout: %s (%.0fs)", cmd_display, timeout)

        result = CommandResult(
            success=False,
            stdout=stdout,
            stderr=stderr,
            exit_code=-1,
            duration=duration,
            command=cmd_display,
        )
        if check:
            raise CommandTimeout(cmd_display, timeout) from exc

    except FileNotFoundError as exc:
        duration = time.monotonic() - t0
        msg = str(exc)
        logger.error("exec not-found: %s (%s)", cmd_display, msg)

        result = CommandResult(
            success=False,
            stdout="",
            stderr=msg,
            exit_code=127,
            duration=duration,
            command=cmd_display,
        )

    except OSError as exc:
        duration = time.monotonic() - t0
        msg = str(exc)
        logger.error("exec os-error: %s (%s)", cmd_display, msg)

        result = CommandResult(
            success=False,
            stdout="",
            stderr=msg,
            exit_code=1,
            duration=duration,
            command=cmd_display,
        )

    if check and not result.success:
        raise CommandError(result)

    return result


# ---------------------------------------------------------------------------
# Sudo wrapper
# ---------------------------------------------------------------------------

def run_with_sudo(
    cmd: Union[str, List[str], Sequence[str]],
    *,
    timeout: float = 120,
    **kwargs: Any,
) -> CommandResult:
    """Execute *cmd* with elevated privileges.

    On Unix, prepends ``sudo`` if the current process is not root.
    On Windows, attempts ``runas`` via PowerShell ``Start-Process``.

    Extra keyword arguments are forwarded to :func:`run_command`.
    """
    import platform as _platform

    kwargs.setdefault("timeout", timeout)

    # Already root?  Just run directly.
    system = _platform.system()
    if system != "Windows":
        try:
            if os.geteuid() == 0:
                return run_command(cmd, **kwargs)
        except AttributeError:
            pass

    # Build the elevated command
    if system == "Windows":
        original = _command_str(cmd)
        elevated = [
            "powershell", "-NoProfile", "-Command",
            f"Start-Process -Verb RunAs -FilePath powershell "
            f"-ArgumentList '-Command {original}' -Wait -PassThru",
        ]
    else:
        original_args = _coerce_command(cmd)
        elevated = ["sudo"] + original_args

    logger.debug("exec (sudo): %s", _command_str(elevated))
    return run_command(elevated, **kwargs)


# ---------------------------------------------------------------------------
# PATH inspection helpers
# ---------------------------------------------------------------------------

def check_command(cmd: str) -> bool:
    """Return ``True`` if *cmd* is found on ``$PATH``."""
    return shutil.which(cmd) is not None


def get_command_path(cmd: str) -> Optional[str]:
    """Return the absolute path to *cmd*, or ``None`` if not found."""
    return shutil.which(cmd)
