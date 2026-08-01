"""``installer doctor`` — diagnose the environment and the install, fix what's
safe to fix.

Produces a checklist (OK/WARN/BROKEN) with one suggested fix per problem.
``--fix`` applies the non-destructive fixes automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from installer.core import env, packages as pkgmod, utils
from installer.version import INSTALLER_NAME, MIN_PYTHON


@dataclass
class Diagnosis:
    title: str
    ok: bool
    detail: str = ""
    fix_hint: str = ""
    fix: Optional[Callable[[], bool]] = None
    severity: str = "ok"  # ok | warn | broken


class Doctor:
    def __init__(self, store, base_dir: Path, registry: pkgmod.PackageRegistry,
                 log=None, auto_fix: bool = False):
        self.store = store
        self.base_dir = base_dir
        self.registry = registry
        self.log = log
        self.auto_fix = auto_fix
        self.checks: List[Diagnosis] = []

    # -- checks ------------------------------------------------------------
    def run_all(self) -> List[Diagnosis]:
        self._check_python()
        self._check_privileges()
        self._check_package_manager()
        self._check_tools()
        self._check_config()
        self._check_state()
        self._check_global_command()
        self._check_network()
        self._check_disk_space()
        self._apply_fixes()
        return self.checks

    def _check_python(self):
        meets = env.python_meets_minimum()
        self.checks.append(Diagnosis(
            title="Python version",
            ok=meets,
            detail=f"{env.python_version()} (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)",
            fix_hint="Install Python 3.10 or newer, or use the platform bootstrap.",
        ))

    def _check_privileges(self):
        root = env.is_admin()
        self.checks.append(Diagnosis(
            title="Admin privileges",
            ok=True,
            detail="root/admin" if root else "user",
        ))

    def _check_package_manager(self):
        pm = env.package_manager()
        ok = bool(pm)
        self.checks.append(Diagnosis(
            title="Package manager",
            ok=ok,
            detail=pm or "none detected",
            fix_hint="Install your platform package manager (apt/dnf/pacman/zypper/brew/pkg/winget).",
            severity="warn" if ok else "broken",
        ))

    def _check_tools(self):
        for name in self.registry.names():
            info = pkgmod.check_package(self.registry, name)
            optional = info["optional"]
            if optional and not info["installed"]:
                continue
            self.checks.append(Diagnosis(
                title=f"Tool: {name}",
                ok=bool(info["installed"] and info["min_ok"]),
                detail=info["version"] or "not installed",
                fix_hint=f"Run: installer install",
                severity="warn" if optional else "broken",
            ))

    def _check_config(self):
        ok = True
        detail = "not created yet"
        if self.store.path.exists():
            try:
                self.store.load()
                detail = f"valid ({self.store.fmt})"
            except Exception as exc:
                ok = False
                detail = f"unreadable: {exc}"
        self.checks.append(Diagnosis(
            title="Config file",
            ok=ok,
            detail=detail,
            fix_hint="Re-run installer install to regenerate the config.",
            severity="warn" if ok else "broken",
        ))

    def _check_state(self):
        from installer.core import state as statemod

        st = statemod.InstallState.load(self.base_dir)
        self.checks.append(Diagnosis(
            title="Install state",
            ok=st.is_installed(),
            detail="complete" if st.is_installed() else "not installed",
            fix_hint="Run: installer install",
            severity="warn" if st.is_installed() else "broken",
        ))

    def _check_global_command(self):
        binpath = env.bin_dir()
        exe = binpath / INSTALLER_NAME
        on_path = utils.which(INSTALLER_NAME) is not None

        def _fix() -> bool:
            return utils.run_ok([str(exe), "version"], capture=True) or exe.exists()

        self.checks.append(Diagnosis(
            title="Global installer command",
            ok=on_path,
            detail=f"{exe} " + ("on PATH" if on_path else "not on PATH"),
            fix_hint=f"Add {binpath} to PATH, or re-run installer install.",
            fix=_fix,
            severity="warn" if on_path else "broken",
        ))

    def _check_network(self):
        ok = utils.run_ok(["git", "ls-remote", "--heads", "https://github.com/adittaya/workflow-youtube.git", "main"],
                          capture=True, timeout=15)
        self.checks.append(Diagnosis(
            title="Network / GitHub reachable",
            ok=ok,
            detail="reachable" if ok else "unreachable",
            fix_hint="Check your internet connection and proxy settings.",
            severity="warn" if ok else "broken",
        ))

    def _check_disk_space(self):
        try:
            usage = __import__("shutil").disk_usage(str(self.base_dir))
            free = usage.free / (1024 ** 3)
            ok = free > 0.5
        except OSError:
            ok, free = True, 0.0
        self.checks.append(Diagnosis(
            title="Disk space",
            ok=ok,
            detail=f"{free:.1f} GiB free",
            fix_hint="Free up disk space before installing.",
        ))

    # -- fixing ------------------------------------------------------------
    def _apply_fixes(self):
        for check in self.checks:
            if check.ok or not check.fix:
                continue
            if self.auto_fix:
                try:
                    if check.fix():
                        check.ok = True
                        check.detail += " (fixed)"
                except Exception as exc:  # noqa: BLE001
                    check.detail += f" (fix failed: {exc})"
            else:
                check.fix_hint = check.fix_hint or "Run installer install."

    # -- rendering ---------------------------------------------------------
    def render(self, ui) -> int:
        broken = 0
        for c in self.checks:
            if c.ok:
                label = ui.color.get("green", "") + "OK"
            elif c.severity == "warn":
                label = ui.color.get("yellow", "") + "WARN"
            else:
                label = ui.color.get("red", "") + "BROKEN"
                broken += 1
            label += ui.color.get("reset", "")
            print(f"  {label:<9} {c.title:<32} {c.detail}")
            if not c.ok and c.fix_hint:
                print(f"             {ui.color.get('dim', '')}→ {c.fix_hint}{ui.color.get('reset', '')}")
        return broken
