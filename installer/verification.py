"""Verification: check installed tools and the installation itself.

Produces a table of:

    Status    Tool       Version    Requirement
    Installed git        2.43.0     ok
    Missing   ffmpeg      -          system package

The same checks power ``installer verify`` and the post-install summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from installer.core import env, packages as pkgmod


@dataclass
class Check:
    name: str
    command: str
    version: Optional[str]
    installed: bool
    ok: bool
    detail: str = ""

    @property
    def status(self) -> str:
        return "Installed" if self.installed else "Missing"


def verify_tools(registry: pkgmod.PackageRegistry, names: Optional[List[str]] = None) -> List[Check]:
    """Check presence/version of logical package names (or all defined)."""
    names = names or registry.names()
    checks: List[Check] = []
    for name in names:
        if name not in registry.names():
            continue
        info = pkgmod.check_package(registry, name)
        min_ok = info["min_ok"]
        detail = ""
        if info["optional"] and not info["installed"]:
            # Optional tools never block a successful install.
            ok, detail = True, "optional"
        else:
            ok = info["installed"] and min_ok
            if info["installed"] and not min_ok:
                detail = f"requires {info['min_version']}+"
        checks.append(Check(
            name=name, command=info["verify"] or name,
            version=info["version"], installed=info["installed"], ok=ok,
            detail=detail,
        ))
    for pip in registry.pip_packages():
        if not pip.verify:
            continue
        version = env.version_of(pip.verify)
        checks.append(Check(name=pip.name, command=pip.verify, version=version,
                            installed=version is not None, ok=version is not None,
                            detail="pip package" if version is None else ""))
    return checks


def verify_installation(config_path: Path, base_dir, registry) -> List[Check]:
    """High-level integrity checks of the installed environment."""
    checks: List[Check] = []
    from installer.core import state as statemod

    st = statemod.InstallState.load(base_dir)
    checks.append(Check("install state", "", "complete" if st.is_installed() else "incomplete",
                        st.is_installed(), st.is_installed(),
                        detail=f"state: {base_dir / 'state.json'}"))

    checks.append(Check("config", "", "present" if config_path.exists() else "missing",
                        config_path.exists(), config_path.exists(),
                        detail=str(config_path)))

    binpath = env.bin_dir()
    from installer.version import INSTALLER_NAME, TUI_NAME

    installer_bin = binpath / INSTALLER_NAME
    present = installer_bin.exists()
    checks.append(Check("installer CLI", str(installer_bin),
                        "" , present, present,
                        detail="global command" if present else "not found on PATH"))

    tui_bin = binpath / TUI_NAME
    present = tui_bin.exists()
    checks.append(Check("TUI command", str(tui_bin),
                        "", present, present,
                        detail="global command" if present else "not found on PATH"))

    checks.extend(verify_tools(registry, registry.names()))
    return checks


def render_report(checks: Sequence[Check], ui) -> None:
    """Print a formatted verification table."""
    headers = ("Status", "Tool", "Version", "Requirement")
    rows: List[List[str]] = []
    for c in checks:
        status = ui.color.get("green", "") + "Installed" if c.installed else ui.color.get("red", "") + "Missing"
        status += ui.color.get("reset", "")
        version = c.version or "—"
        req = c.detail if c.detail else ("ok" if c.ok else "")
        if not c.installed and not c.detail:
            req = "install required"
        rows.append([status, c.name, version, req])
    widths = [max(len(r[i]) for r in rows + [list(headers)]) for i in range(4)]
    fmt = "  " + "   ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  " + "-" * (sum(widths) + 9))
    for row in rows:
        print(fmt.format(*row))


def summary_report(checks: Sequence[Check]) -> Tuple[int, int]:
    ok = sum(1 for c in checks if c.ok)
    return ok, len(checks)
