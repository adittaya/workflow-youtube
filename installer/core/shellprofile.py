"""Safe, idempotent modification of shell profiles.

Supports bash, zsh, sh, fish and PowerShell (pwsh / Windows PowerShell).
Never duplicates existing entries; only appends the minimal lines needed and
can remove exactly what it added (for uninstall). Non-interactive use is safe:
profiles are only ever edited via ``add_*`` calls that are explicit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from installer.core import env, utils

_PATH_DIR_RE = None  # built lazily


class ShellProfile:
    def __init__(self, shell: Optional[str] = None, home: Optional[Path] = None):
        self.shell = shell or env.shell()
        self.home = Path(home) if home else env.home_dir()
        self._log = None

    # -- public API --------------------------------------------------------
    def files(self) -> List[Path]:
        """Candidate profile files for the detected shell (may not exist yet)."""
        if self.shell == "bash":
            return [self.home / ".bashrc", self.home / ".profile"]
        if self.shell == "zsh":
            return [self.home / ".zshrc"]
        if self.shell == "fish":
            return [self.home / ".config" / "fish" / "config.fish"]
        if self.shell == "sh":
            return [self.home / ".profile"]
        if self.shell == "pwsh":
            docs = Path(os.environ.get("USERPROFILE", self.home)) / "Documents"
            return [docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1"]
        return []

    def add_path(self, directory: Path) -> List[Path]:
        """Ensure ``directory`` is prepended to PATH in the profiles.

        Returns the list of profiles that were modified.
        """
        changed = []
        for path in self.files():
            if self._path_present(path, directory):
                continue
            lines = self._existing_lines(path)
            lines.extend(self._path_line(directory))
            self._write(path, lines)
            changed.append(path)
        return changed

    def add_export(self, key: str, value: str) -> List[Path]:
        """Ensure ``KEY="value"`` is exported in the profiles (idempotent)."""
        changed = []
        for path in self.files():
            if self._export_present(path, key):
                continue
            lines = self._existing_lines(path)
            lines.extend(self._export_line(key, value))
            self._write(path, lines)
            changed.append(path)
        return changed

    def remove_path(self, directory: Path) -> List[Path]:
        """Remove every line that adds ``directory`` to PATH."""
        changed = []
        for path in self.files():
            if not path.exists():
                continue
            kept = [ln for ln in self._existing_lines(path) if not self._line_refs_path(ln, directory)]
            if len(kept) != len(self._existing_lines(path)):
                self._write(path, kept)
                changed.append(path)
        return changed

    def remove_export(self, key: str) -> List[Path]:
        """Remove every line that exports or sets ``key``."""
        changed = []
        for path in self.files():
            if not path.exists():
                continue
            kept = [ln for ln in self._existing_lines(path) if not self._line_sets_key(ln, key)]
            if len(kept) != len(self._existing_lines(path)):
                self._write(path, kept)
                changed.append(path)
        return changed

    # -- line generators ---------------------------------------------------
    def _path_line(self, directory: Path) -> List[str]:
        d = str(directory)
        if self.shell == "fish":
            return [f'fish_add_path "{d}"']
        if self.shell == "pwsh":
            return [f'$env:Path = "{d}" + [System.IO.Path]::PathSeparator + $env:Path']
        return [f'export PATH="{d}:$PATH"']

    def _export_line(self, key: str, value: str) -> List[str]:
        if self.shell == "fish":
            return [f'set -gx {key} "{value}"']
        if self.shell == "pwsh":
            return [f'$env:{key} = "{value}"']
        return [f'export {key}="{value}"']

    # -- detection helpers -------------------------------------------------
    def _existing_lines(self, path: Path) -> List[str]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def _write(self, path: Path, lines: List[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        utils.atomic_write(path, ("\n".join(lines) + ("\n" if lines else "")), mode=0o644)

    def _path_present(self, path: Path, directory: Path) -> bool:
        return any(self._line_refs_path(ln, directory) for ln in self._existing_lines(path))

    def _export_present(self, path: Path, key: str) -> bool:
        return any(self._line_sets_key(ln, key) for ln in self._existing_lines(path))

    def _line_sets_key(self, line: str, key: str) -> bool:
        if self.shell == "fish":
            return bool(re.match(rf'^\s*set\s+(-[a-zA-Z]+\s+)*\b{re.escape(key)}\b\s', line))
        if self.shell == "pwsh":
            return bool(re.match(rf'^\s*\$env:{re.escape(key)}\s*=', line))
        return bool(re.match(rf'^\s*(export\s+)?{re.escape(key)}\s*=', line))

    def _line_refs_path(self, line: str, directory: Path) -> bool:
        d = str(directory)
        if self.shell == "fish":
            return "fish_add_path" in line and d in line
        if self.shell == "pwsh":
            return "$env:Path" in line and d in line
        return ("PATH" in line) and (d in line)
