"""Clean uninstall: remove installed files, global commands and PATH edits.

User data (runtime state such as ``~/.yt-mirror``) is left untouched unless
the user explicitly confirms its removal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from installer.core import env, shellprofile, utils
from installer.version import APP_NAME, INSTALLER_NAME


@dataclass
class UninstallResult:
    removed_dirs: List[Path] = field(default_factory=list)
    removed_bins: List[Path] = field(default_factory=list)
    edited_profiles: List[Path] = field(default_factory=list)
    removed_config: bool = False


def uninstall(base_dir: Path, config_dir: Path, *,
              remove_config: bool = False,
              data_dir: Path = None,
              log=None) -> UninstallResult:
    result = UninstallResult()

    # 1. Global command shims.
    binpath = env.bin_dir()
    for name in (INSTALLER_NAME, APP_NAME, "VPLINKYT"):
        p = binpath / name
        if p.exists() or p.is_symlink():
            utils.remove_path(p)
            result.removed_bins.append(p)

    # 2. Installed source copy.
    if base_dir.exists():
        utils.remove_path(base_dir)
        result.removed_dirs.append(base_dir)

    # 3. PATH / env edits in shell profiles.
    prof = shellprofile.ShellProfile()
    for p in prof.remove_path(binpath):
        result.edited_profiles.append(p)
    for p in prof.remove_export("YT_MIRROR_HOME"):
        result.edited_profiles.append(p)

    # 4. Config (optional).
    if remove_config and config_dir.exists():
        utils.remove_path(config_dir)
        result.removed_config = True

    if log:
        log.info(f"uninstalled from {base_dir}")
        if result.removed_config:
            log.info(f"config removed from {config_dir}")
        if data_dir and data_dir.exists():
            log.info(f"user data kept at {data_dir} (use --purge to remove)")

    return result
