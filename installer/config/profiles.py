"""
Shell profile management.
Safely modifies shell profiles (.bashrc, .zshrc, .profile, fish config, PowerShell profile).
Never duplicates entries.
"""
import os
import shutil
from pathlib import Path
from typing import Optional

from installer.core.platform import PlatformInfo, detect
from installer import logging as log


def _profile_paths(info: PlatformInfo) -> dict[str, Path]:
    home = Path(info.home)
    return {
        "bash": home / ".bashrc",
        "zsh": home / ".zshrc",
        "fish": home / ".config" / "fish" / "config.fish",
        "profile": home / ".profile",
    }


def _powershell_profile() -> Optional[Path]:
    doc = os.environ.get("DOCUMENTS", "")
    if not doc:
        doc = str(Path.home() / "Documents")
    base = Path(doc) / "WindowsPowerShell"
    if not base.exists():
        base = Path.home() / ".config" / "powershell"
    return base / "profile.ps1" if base.exists() else None


def add_path(info: PlatformInfo, new_path: str, shell: Optional[str] = None):
    """Add a directory to PATH in the appropriate shell profile."""
    shell = shell or info.shell
    profiles = _profile_paths(info)
    profile = profiles.get(shell)

    if shell == "powershell":
        profile = _powershell_profile()

    if not profile:
        log.warn(f"No profile found for {shell}")
        return

    export_line = ""
    if shell == "fish":
        export_line = f"set -gx PATH {new_path} $PATH"
    elif shell == "powershell":
        export_line = f'$env:PATH = "{new_path};$env:PATH"'
    else:
        export_line = f'export PATH="{new_path}:$PATH"'

    _add_line_once(profile, export_line)


def add_env(info: PlatformInfo, key: str, value: str, shell: Optional[str] = None):
    """Set an environment variable in the shell profile."""
    shell = shell or info.shell
    profiles = _profile_paths(info)
    profile = profiles.get(shell)

    if shell == "powershell":
        profile = _powershell_profile()

    if not profile:
        log.warn(f"No profile found for {shell}")
        return

    export_line = ""
    if shell == "fish":
        export_line = f"set -gx {key} {value}"
    elif shell == "powershell":
        export_line = f'$env:{key} = "{value}"'
    else:
        export_line = f'export {key}="{value}"'

    _add_line_once(profile, export_line)


def _add_line_once(profile: Path, line: str):
    """Add a line to a file if it doesn't already exist."""
    profile.parent.mkdir(parents=True, exist_ok=True)
    if not profile.exists():
        profile.write_text(f"#!/usr/bin/env {profile.suffix.lstrip('.') or 'bash'}\n")

    existing = profile.read_text().split("\n")
    # Check if line already exists (with or without quotes variations)
    for existing_line in existing:
        if _lines_match(existing_line.strip(), line):
            log.debug(f"Line already exists in {profile.name}: {line}")
            return

    with open(profile, "a") as f:
        f.write(f"\n# Added by VPLink Installer\n{line}\n")
    log.success(f"Added to {profile.name}: {line}")


def _lines_match(existing: str, new: str) -> bool:
    """Check if two profile lines are equivalent (accounting for quote variations)."""
    import re
    # Normalize quotes
    existing_norm = re.sub(r"['\"`]", "", existing)
    new_norm = re.sub(r"['\"`]", "", new)
    return existing_norm == new_norm


def remove_line(profile: Path, pattern: str):
    """Remove lines matching a pattern from a profile file."""
    if not profile.exists():
        return
    lines = profile.read_text().split("\n")
    filtered = [l for l in lines if pattern not in l]
    profile.write_text("\n".join(filtered).strip() + "\n")


def remove_path(info: PlatformInfo, old_path: str, shell: Optional[str] = None):
    """Remove a PATH entry from shell profile."""
    shell = shell or info.shell
    profiles = _profile_paths(info)
    profile = profiles.get(shell)
    if not profile:
        return
    remove_line(profile, old_path)


def remove_env(info: PlatformInfo, key: str, shell: Optional[str] = None):
    """Remove an env var from shell profile."""
    shell = shell or info.shell
    profiles = _profile_paths(info)
    profile = profiles.get(shell)
    if not profile:
        return
    remove_line(profile, f"export {key}=")
    remove_line(profile, f"set -gx {key}")
    remove_line(profile, f"$env:{key}")
