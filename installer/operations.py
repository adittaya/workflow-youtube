"""Installation orchestration: the staged install pipeline.

Each stage is recorded in the install state and the rollback journal. A failure
in a critical stage triggers rollback of everything done so far; a failure in a
non-critical stage (e.g. an optional package) is logged and the install
continues.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, Tuple

from installer.core import config as cfgmod
from installer.core import env, packages as pkgmod, shellprofile, state as statemod, utils
from installer import rollback as rollmod, verification
from installer.version import APP_NAME, INSTALLER_NAME, MIN_PYTHON, TUI_NAME, __version__


def default_dirs(app: str = APP_NAME):
    cfg_dir = env.config_home(INSTALLER_NAME)
    data_dir = env.data_home(app)
    install_dir = data_dir / "src"
    return cfg_dir, data_dir, install_dir


def resolve_dirs(config: cfgmod.Config):
    """Actual dirs to use, honouring any install_dir/data_dir config overrides
    (``installer config set install_dir …``) with platform defaults."""
    cfg_dir = Path(env.config_home(INSTALLER_NAME))
    data_dir = Path(config.get("data_dir") or env.data_home(APP_NAME)).expanduser()
    install_dir = Path(config.get("install_dir") or (data_dir / "src")).expanduser()
    return cfg_dir, data_dir, install_dir


def defaults() -> dict:
    """Default installer configuration."""
    cfg_dir, data_dir, install_dir = default_dirs()
    return {
        "install_dir": str(install_dir),
        "data_dir": str(data_dir),
        "mirror_home": str(env.home_dir() / ".yt-mirror"),
        "source_url": "",
        "shell_profile": "ask",           # ask | yes | no
        "upgrade": False,
        "packages": ["git", "python", "ffmpeg", "yt-dlp"],
        "optional_packages": ["nodejs", "docker", "chromium", "vscode"],
        "env": {},
    }


def load_config() -> cfgmod.Config:
    cfg_dir, _, _ = default_dirs()
    store = cfgmod.ConfigStore(INSTALLER_NAME, "config.json", "json", cfg_dir)
    config = store.load()
    # User config overrides defaults (config.json wins).
    merged = cfgmod.Config(defaults()).merged(config.to_dict())
    return cfgmod.Config(merged)


def save_config(config: cfgmod.Config) -> None:
    cfg_dir, _, _ = default_dirs()
    store = cfgmod.ConfigStore(INSTALLER_NAME, "config.json", "json", cfg_dir)
    store.save(config)


# --------------------------------------------------------------------------
# Source acquisition
# --------------------------------------------------------------------------

def find_local_source() -> Optional[Path]:
    """If we're running from a repo checkout, use it as the source."""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent,  # repo root when run in-place
    ]
    for c in candidates:
        if (c / "yt_auto.py").exists():
            return c
    return None


def copy_project(src: Path, dest: Path, log=None) -> None:
    """Copy the project source (code, scripts, installer package) to ``dest``.

    The destination is treated as an installer-managed copy: files the source
    no longer ships are removed so a renamed/deleted module can never shadow
    the current one. Re-installing from the installed copy is a no-op
    (src == dest).
    """
    src, dest = src.resolve(), dest.resolve()
    if src == dest:
        if log:
            log.debug("source already at destination; nothing to copy")
        return
    dest.mkdir(parents=True, exist_ok=True)

    patterns = ("*.py", "*.sh", "*.txt", "*.sql")
    src_files = {}
    for pattern in patterns:
        for f in src.glob(pattern):
            if f.name.startswith("test_"):
                continue
            src_files[f.name] = f

    for pattern in patterns:
        for f in dest.glob(pattern):
            if f.name in src_files:
                continue
            if log:
                log.debug(f"removing stale file: {f.name}")
            try:
                f.unlink()
            except OSError:
                pass

    for name, f in src_files.items():
        try:
            shutil.copy2(f, dest / name)
        except OSError:
            pass

    # Installer package (excluding tests/caches so installs stay lean). Fully
    # managed: replace it wholesale so stale installer modules never linger.
    src_pkg = src / "installer"
    if src_pkg.is_dir():
        dst_pkg = dest / "installer"
        if dst_pkg.exists():
            utils.remove_path(dst_pkg)
        shutil.copytree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "tests", ".pytest_cache"))
    if log:
        log.debug(f"copied project source from {src} to {dest}")


def ensure_source(config: cfgmod.Config, log=None) -> Tuple[Path, str]:
    """Return (source_dir, source_kind) — local checkout or fresh clone."""
    local = find_local_source()
    if local:
        return local, "local"
    url = config.get("source_url", "")
    if not url:
        raise RuntimeError(
            "no local checkout found and no source_url configured; "
            "run the installer from a clone of the repository")
    target = Path(config["install_dir"]).parent / ".repo"
    utils.remove_path(target)
    res = utils.run(["git", "clone", "--depth", "1", url, str(target)], capture=True)
    if res.returncode != 0:
        raise RuntimeError(f"git clone failed: {res.stderr or res.stdout}")
    return target, "git"


# --------------------------------------------------------------------------
# Package / pip installs
# --------------------------------------------------------------------------

def install_pip_requirements(requirements: Path, log=None) -> bool:
    base = ["python3", "-m", "pip"]
    attempts = [
        base + ["install", "--break-system-packages", "-r", str(requirements)],
        base + ["install", "-r", str(requirements)],
        base + ["install", "--user", "-r", str(requirements)],
    ]
    for argv in attempts:
        if log:
            log.debug("$ " + " ".join(argv))
        res = utils.run(argv, capture=True, timeout=1800)
        if res.returncode == 0:
            return True
    return False


def install_system_packages(pm, registry, names: list, log=None) -> Tuple[bool, list]:
    """Install logical package names via the platform manager.

    Returns (all_ok, missing_logical_names).
    """
    concrete, unmapped = registry.system_install_names(pm.name, names)
    if unmapped:
        log.warn(f"no mapping for: {', '.join(unmapped)}")
    if not concrete:
        return not unmapped, unmapped
    if not pm.install(concrete):
        log.error(pm.error_hint(concrete))
        return False, names
    return True, []


# --------------------------------------------------------------------------
# Global commands
# --------------------------------------------------------------------------

def install_global_commands(src_dir: Path, log=None) -> Tuple[Path, Path, Path]:
    """Create the ``installer``, ``yt-auto`` and ``YOUTUBE`` shims; return
    their paths (installer, yt-auto, YOUTUBE)."""
    binpath = env.bin_dir()
    binpath.mkdir(parents=True, exist_ok=True)

    installer_shim = binpath / INSTALLER_NAME
    utils.atomic_write(installer_shim,
        "#!/usr/bin/env bash\n"
        f"cd \"{src_dir}\" && exec python3 -m installer \"$@\"\n", mode=0o755)

    yt_auto_shim = binpath / APP_NAME
    utils.atomic_write(yt_auto_shim,
        "#!/usr/bin/env bash\n"
        f"exec python3 \"{src_dir}/yt_auto.py\" \"$@\"\n", mode=0o755)

    tui_shim = binpath / TUI_NAME
    utils.atomic_write(tui_shim,
        "#!/usr/bin/env bash\n"
        f"exec python3 \"{src_dir}/tui.py\" \"$@\"\n", mode=0o755)
    # Compatibility symlink used by older launchers.
    compat = binpath / "VPLINKYT"
    try:
        if compat.exists() or compat.is_symlink():
            utils.remove_path(compat)
        compat.symlink_to(yt_auto_shim)
    except OSError:
        pass
    if log:
        log.debug(f"installed shims: {installer_shim}, {yt_auto_shim}, {tui_shim}")
    return installer_shim, yt_auto_shim, tui_shim


# --------------------------------------------------------------------------
# The install pipeline
# --------------------------------------------------------------------------

def run_install(ui, config: cfgmod.Config, *, non_interactive: bool = False,
                dry_run: bool = False) -> int:
    from installer.core.logging import get_logger

    log = get_logger()
    cfg_dir, data_dir, install_dir = resolve_dirs(config)
    base_dir = cfg_dir
    st = statemod.InstallState.load(base_dir)
    journal = rollmod.RollbackJournal(base_dir / "rollback.json").load()

    registry = pkgmod.PackageRegistry.from_yaml(_packages_path())
    pm = env.package_manager()
    manager = None
    if pm:
        from installer.platforms import get_installer

        manager = get_installer(log)

    ui.ok(f"Detecting OS → {env.summary()}")
    if dry_run:
        ui.dim("dry-run: no system changes will be made")
    if not env.python_meets_minimum():
        ui.error(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, found {env.python_version()}")
        return 1
    if not manager:
        ui.error("No supported package manager detected.")
        return 1

    # Stage: system packages (critical — a failure aborts the install)
    st.begin_stage("system_packages")
    requested = list(config.get("packages", []))
    missing = [n for n in requested if not pkgmod.check_package(registry, n)["installed"]]
    if missing:
        concrete, _ = registry.system_install_names(pm, missing)
        if dry_run:
            ui.dim(f"would install via {pm}: {', '.join(concrete)}")
        else:
            with ui.spinner(f"Installing {' '.join(missing)} via {pm}"):
                ok, _ = install_system_packages(manager, registry, missing, log)
            if ok:
                ui.ok(f"Installed: {', '.join(missing)}")
            else:
                ui.error(f"Could not install required packages: {', '.join(missing)}")
                st.end_stage("system_packages", "failed", ", ".join(missing))
                st.save()
                journal.rollback(log)
                return 1
    st.end_stage("system_packages", "done")
    st.save()

    # Stage: copy source
    st.begin_stage("copy_source")
    try:
        src, kind = ensure_source(config, log)
        if dry_run:
            ui.dim(f"source: {kind} ({src})")
        else:
            copy_project(src, install_dir, log)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"Source copy failed: {exc}")
        st.end_stage("copy_source", "failed", str(exc))
        st.save()
        journal.rollback(log)
        return 1
    st.end_stage("copy_source", "done", kind)
    st.save()

    # Stage: pip requirements
    st.begin_stage("pip_requirements")
    req_file = install_dir / "requirements.txt"
    if dry_run:
        ui.dim(f"would pip-install: {req_file.name}")
    elif req_file.exists() and not install_pip_requirements(req_file, log):
        ui.warn("Python dependencies could not be installed (pip). "
                "Run 'installer repair' after fixing pip, or install them manually.")
        st.end_stage("pip_requirements", "failed",
                     "pip install failed; run 'installer repair'")
        st.save()
    else:
        st.end_stage("pip_requirements", "done")
        st.save()

    # Stage: config + data dirs
    st.begin_stage("config")
    cfg_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    mirror = Path(config["mirror_home"]).expanduser()
    for sub in ("bgm", "separated", "processed"):
        (mirror / sub).mkdir(parents=True, exist_ok=True)
    config.set("install_dir", str(install_dir))
    config.set("data_dir", str(data_dir))
    save_config(config)
    st.end_stage("config", "done")
    st.save()

    # Stage: global commands
    st.begin_stage("global_commands")
    installer_bin, yt_auto_bin, tui_bin = install_global_commands(install_dir, log)
    journal.record_remove(installer_bin, "installer shim")
    journal.record_remove(yt_auto_bin, "yt-auto shim")
    journal.record_remove(tui_bin, "YOUTUBE shim")
    st.end_stage("global_commands", "done")
    st.save()

    # Stage: PATH configuration (shell profiles)
    st.begin_stage("shell_profile")
    if not dry_run:
        _configure_path(ui, config, log)
    else:
        ui.dim("would update shell profile PATH")
    st.end_stage("shell_profile", "done")
    st.save()

    st.mark_installed(__version__)
    st.save()
    journal.clear()

    ui.ok("Writing Config")
    ui.ok("Installation Complete")
    ui.success_summary([
        ("Install dir", str(install_dir)),
        ("Config dir", str(cfg_dir)),
        ("Commands", f"{INSTALLER_NAME}, {APP_NAME}, {TUI_NAME} in {env.bin_dir()}"),
        ("Mirror data", config["mirror_home"]),
        ("Next", "run 'installer doctor' or 'installer verify'"),
    ])
    return 0


def _configure_path(ui, config: cfgmod.Config, log) -> None:
    """Add the bin dir to PATH (per config preference, or ask once)."""
    binpath = env.bin_dir()
    prof = shellprofile.ShellProfile()
    pref = config.get("shell_profile", "ask")
    if pref == "no":
        ui.dim("Shell profile edit skipped (shell_profile=no).")
        return
    if pref == "yes" or (pref == "ask" and ui.confirm(
            f"Add {binpath} to PATH in your shell profile?")):
        changed = prof.add_path(binpath)
        for extra_key, extra_val in config.get("env", {}).items():
            changed += prof.add_export(extra_key, str(extra_val))
        if changed:
            ui.ok("PATH updated — open a new terminal (or source your profile).")
        else:
            ui.dim("PATH already configured.")


def _packages_path() -> Path:
    return Path(__file__).resolve().parent / "packages.yaml"


# --------------------------------------------------------------------------
# Sub-command implementations used by the CLI
# --------------------------------------------------------------------------

def run_update(ui, config) -> int:
    from installer import update

    log = None
    current = __version__
    ui.info(f"Current version: {current}")
    latest = update.fetch_latest_release(log)
    if latest is None:
        # No GitHub release published — this project ships from the main
        # branch, so fall back to fetching the latest main-branch source.
        ui.warn("No GitHub release published (this project ships from main).")
        if not ui.confirm("Fetch the latest main-branch source and update now?"):
            return 0
        ok, msg = update.perform_update(Path(config["install_dir"]), log)
        if ok:
            ui.ok(f"Updated: {msg}")
            return 0
        ui.error(f"Update failed: {msg}")
        return 1
    ui.info(f"Latest release:  {latest.tag}")
    if not update.is_newer(latest, current):
        ui.ok("Already up to date.")
        return 0
    if latest.body and ui.interactive:
        ui.title("Changelog")
        ui.line(update.changelog(latest))
    if ui.confirm(f"Upgrade to {latest.tag} now?"):
        ok, msg = update.perform_update(Path(config["install_dir"]), log)
        if ok:
            ui.ok(f"Updated: {msg}")
            return 0
        ui.error(f"Update failed: {msg}")
        return 1
    return 0


def run_verify(ui, config) -> int:
    cfg_dir, _, install_dir = resolve_dirs(config)
    registry = pkgmod.PackageRegistry.from_yaml(_packages_path())
    cfg_path = cfg_dir / "config.json"
    # Install state lives in the config home — verify against that, not the
    # data dir (passing the wrong base_dir made the check always 'incomplete').
    checks = verification.verify_installation(cfg_path, cfg_dir, registry)
    verification.render_report(checks, ui)
    ok, total = verification.summary_report(checks)
    ui.line()
    if ok == total:
        ui.ok(f"All {total} checks passed.")
        return 0
    ui.warn(f"{ok}/{total} checks passed. Run 'installer doctor' for details.")
    return 1 if ok < total else 0


def run_status(ui, config) -> int:
    cfg_dir, data_dir, install_dir = resolve_dirs(config)
    st = statemod.InstallState.load(cfg_dir)
    ui.title("Environment")
    for k, v in env.display_environment().items():
        print(f"  {k:<18} {v}")
    ui.title("Installation")
    print(f"  {'state':<18} {'installed' if st.is_installed() else 'not installed'}")
    print(f"  {'source':<18} {install_dir}")
    print(f"  {'data dir':<18} {data_dir}")
    print(f"  {'config':<18} {env.config_home(INSTALLER_NAME)}")
    failed = st.needs_repair()
    if failed:
        ui.warn(f"failed stages: {', '.join(failed)} — run 'installer repair'")
    return 0


def run_logs(ui, lines: int = 60) -> int:
    from installer.core.logging import get_logger

    log = get_logger()
    path = log.log_file()
    if not path or not path.exists():
        ui.warn("No log file yet.")
        return 1
    ui.line(f"Log file: {path}")
    ui.line("-" * 60)
    print(log.tail(path, lines))
    return 0


def run_repair(ui, config) -> int:
    """Re-run install stages that are incomplete or failed, non-destructively."""
    ui.title("Repairing installation")
    return run_install(ui, config)


def run_doctor(ui, config, auto_fix: bool) -> int:
    from installer.doctor import Doctor

    cfg_dir, _, _ = default_dirs()
    store = cfgmod.ConfigStore(INSTALLER_NAME, "config.json", "json", cfg_dir)
    registry = pkgmod.PackageRegistry.from_yaml(_packages_path())
    doc = Doctor(store, cfg_dir, registry, auto_fix=auto_fix)
    doc.run_all()
    ui.title("Doctor report")
    n = doc.render(ui)
    if n == 0:
        ui.ok("All checks passed.")
        return 0
    ui.warn(f"{n} problem(s) found. Use --fix to auto-fix safe items.")
    return 1


def run_uninstall(ui, config, *, remove_config: bool, purge_data: bool) -> int:
    from installer import uninstall

    cfg_dir, data_dir, install_dir = resolve_dirs(config)
    if not ui.confirm("Remove the yt-auto installation? This does NOT touch ~/.yt-mirror data.", default=False):
        ui.dim("Aborted.")
        return 0
    result = uninstall.uninstall(
        install_dir, cfg_dir,
        remove_config=remove_config,
        data_dir=Path(config["mirror_home"]).expanduser() if purge_data else None)
    for d in result.removed_dirs:
        ui.ok(f"Removed {d}")
    for p in result.edited_profiles:
        ui.ok(f"Cleaned {p}")
    if result.removed_config:
        ui.ok("Config removed.")
    if purge_data and ui.confirm("Also delete ~/.yt-mirror user data? (irreversible)", default=False):
        utils.remove_path(Path(config["mirror_home"]))
        ui.ok("User data removed.")
    ui.ok("Uninstall complete.")
    return 0
