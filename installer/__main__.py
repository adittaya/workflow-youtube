#!/usr/bin/env python3
"""
VPLink 24/7 — Cross-Platform Bootstrap Installer (CLI entry point).

Usage: python3 -m installer install|update|doctor|verify|config|uninstall|logs|status|repair|version
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from installer import __version__, __app_name__, __repo__
from installer.core.platform import detect, is_supported, suggest_install
from installer.platforms import get_platform, detect_platform
from installer.packages import register_packages, is_installed, check_version
from installer.config import Config, ensure_dirs
from installer.config.profiles import add_path, add_env
from installer.downloads import download, validate_url, make_executable
from installer.rollback import RollbackManager, FileBackup
from installer import logging as log
from installer.interactive import confirm, choose, input_text, header as ui_header, Spinner


LOG_DIR = str(Path.home() / ".config" / "vplink" / "logs")


# ── commands ──────────────────────────────────────────────────────────

def cmd_install():
    log.init(LOG_DIR, level="info")
    info = detect()

    ui_header("VPLink 24/7 Bootstrap Installer")
    log.info(f"Platform: {info.os_name}/{info.distribution} ({info.arch})")

    if not is_supported():
        log.warn(f"Platform {info.distribution} is not officially supported")

    ensure_dirs(info)
    register_packages()
    platform = get_platform(info)

    # ---- step 1: update package DB ----
    log.header("Step 1: Updating Package Database")
    with Spinner("Updating package database..."):
        ok = platform.update_package_db()
    if ok:
        log.success("Package database updated")
    else:
        log.info("Skipped (not needed on this platform)")

    # ---- step 2: install core deps ----
    log.header("Step 2: Installing Core Dependencies")
    core_pkgs = ["git", "python3", "curl", "wget"]
    for pkg in core_pkgs:
        installed, ver = is_installed(pkg)
        if installed:
            log.success(f"{pkg}: {ver or 'already installed'}")
        else:
            with Spinner(f"Installing {pkg}..."):
                result = platform.install_package(pkg)
            if result.success:
                log.success(f"{pkg}: {result.version or 'installed'}")
            else:
                log.error(f"{pkg}: {result.error or 'failed'}")
                if not confirm("Continue despite error?"):
                    sys.exit(1)

    # ---- step 3: python packages ----
    log.header("Step 3: Installing Python Packages")
    for pkg in ["flask", "pynacl", "requests", "selenium"]:
        with Spinner(f"Installing {pkg}..."):
            result = platform.install_package(pkg)
        if result.success:
            log.success(f"{pkg}: {result.version or 'installed'}")
        else:
            log.warn(f"{pkg}: {result.error or 'skipped'}")

    # ---- step 4: environment ----
    log.header("Step 4: Configuring Environment")
    bin_dir = info.bin_dir
    if info.os_name != "windows":
        Path(bin_dir).mkdir(parents=True, exist_ok=True)
        add_path(info, bin_dir)

    cfg = Config("vplink", info)
    if not cfg.get("setup_complete"):
        _first_run_wizard(cfg)

    # ---- step 5: verification ----
    log.header("Step 5: Verification")
    from installer.verification import verify_all as do_verify
    for c in do_verify():
        if c["ok"]:
            log.success(f"{c['name']}: {c['version'] or 'ok'}")
        else:
            log.warn(f"{c['name']}: missing")

    print()
    log.header("Installation Complete")
    log.success("VPLink 24/7 environment is ready")
    print(f"  Next steps: vplink247  or  vplink247 web")


def _first_run_wizard(cfg: Config):
    log.info("First-run setup — configure Supabase credentials")
    supabase_url = input_text("Supabase Project URL", "https://")
    supabase_key = input_text("Supabase Anon Key")
    supabase_secret = input_text("Supabase Service Role Key", secret=True)

    if supabase_url and supabase_key and supabase_secret:
        cfg.set("supabase_url", supabase_url)
        cfg.set("supabase_key", supabase_key)
        cfg.set("supabase_secret", supabase_secret)
        add_env(detect(), "SUPABASE_URL", supabase_url)
        add_env(detect(), "SUPABASE_KEY", supabase_key)
        add_env(detect(), "SUPABASE_SECRET", supabase_secret)
    cfg.set("setup_complete", True)
    log.success("Configuration saved")


def cmd_doctor():
    log.init(LOG_DIR)
    info = detect()
    ui_header("System Diagnostics")

    print(f"  OS:        {info.os_name}/{info.distribution} ({info.arch})")
    print(f"  Shell:     {info.shell}")
    print(f"  PKG Mgr:   {info.package_manager}")
    print(f"  Root:      {info.is_root}")
    print(f"  WSL:       {info.is_wsl}")
    print(f"  Docker:    {info.is_docker}")
    print(f"  Systemd:   {info.has_systemd}")
    print()
    print(f"  Config:    {info.config_dir}")
    print(f"  Data:      {info.data_dir}")
    print(f"  Bin:       {info.bin_dir}")
    print()

    from installer.verification import verify_all as do_verify
    results = do_verify()
    for c in results:
        status = f"✓ {c['version']}" if c["ok"] else "✗ missing"
        print(f"  {status:20} {c['name']}")

    failed = sum(1 for c in results if not c["ok"])
    print()
    if failed:
        log.warn(f"{failed} dependencies missing — run: installer install")
    else:
        log.success("System healthy!")


def cmd_update():
    log.init(LOG_DIR)
    ui_header("Self-Update")

    from installer.update import check_latest, get_current_version, update_self, compare_versions
    current = get_current_version()
    latest = check_latest()
    if latest and compare_versions(latest, current) > 0:
        log.info(f"Update available: {current} → {latest}")
        if confirm("Update now?"):
            if update_self():
                log.success(f"Updated to {latest}")
            else:
                log.error("Update failed")
    else:
        log.success(f"Already up to date ({current})")


def cmd_verify():
    log.init(LOG_DIR)
    ui_header("Verification")
    from installer.verification import verify_all as do_verify
    all_ok = True
    for c in do_verify():
        if c["ok"]:
            log.success(f"{c['name']}: {c['version'] or 'present'}")
        else:
            log.error(f"{c['name']}: NOT FOUND")
            all_ok = False
    print()
    log.success("All dependencies verified") if all_ok else log.warn("Some are missing")


def cmd_config():
    info = detect()
    cfg = Config("vplink", info)
    data = cfg.load()
    ui_header("Configuration")
    print(f"  File: {cfg.path()}")
    print()
    if not data:
        log.info("No configuration yet")
        return
    for k, v in data.items():
        if any(s in k.lower() for s in ["secret", "token", "key", "password"]):
            print(f"  {k}: {'*' * 8}")
        else:
            print(f"  {k}: {v}")


def cmd_uninstall():
    ui_header("Uninstall")
    if not confirm("Remove all VPLink configuration and data?", default=False):
        return
    config_dir = Path.home() / ".config" / "vplink"
    data_dir = Path.home() / ".local" / "share" / "vplink"
    for d in [config_dir, data_dir]:
        if d.exists():
            shutil.rmtree(d)
            log.success(f"Removed {d}")
    for cmd in ["/usr/local/bin/vplink247", "/usr/local/bin/installer"]:
        p = Path(cmd)
        if p.exists():
            p.unlink()
            log.success(f"Removed {cmd}")
    log.success("Uninstall complete")


def cmd_logs():
    log_dir = Path(LOG_DIR)
    if not log_dir.exists():
        log.error("No log directory")
        return
    logs = sorted(log_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        log.error("No log files")
        return
    ui_header("Recent Logs")
    for lp in logs[:10]:
        size = lp.stat().st_size
        mtime = time.ctime(lp.stat().st_mtime)
        print(f"  {mtime}  {size:>8}B  {lp.name}")
    print()
    if confirm(f"View latest ({logs[0].name})?"):
        print(logs[0].read_text())


def cmd_status():
    info = detect()
    ui_header(f"{__app_name__} {__version__}")
    print(f"  Platform:  {info.os_name}/{info.distribution} ({info.arch})")
    print(f"  Shell:     {info.shell}")
    print(f"  Config:    {info.config_dir}")
    print(f"  Data:      {info.data_dir}")
    print()

    register_packages()
    for dep in ["git", "python3", "node", "docker", "curl", "wget"]:
        installed, ver = is_installed(dep)
        status = f"✓ {ver}" if installed else "✗ missing"
        print(f"  {status:>20}  {dep}")

    cfg = Config("vplink", info)
    print()
    log.info(f"Config: {cfg.path()}")
    log.success("Configured") if cfg.load() else log.warn("Not configured")


def cmd_repair():
    log.init(LOG_DIR)
    info = detect()
    platform = get_platform(info)
    ui_header("Repair Mode")

    from installer.verification import verify_all as do_verify
    missing = [c for c in do_verify() if not c["ok"]]
    if not missing:
        log.success("Nothing to repair")
        return
    log.warn(f"Repairing {len(missing)} missing dependencies")
    for c in missing:
        with Spinner(f"Installing {c['name']}..."):
            result = platform.install_package(c["package"])
        if result.success:
            log.success(f"{c['name']}: installed")
        else:
            log.error(f"{c['name']}: {result.error or 'failed'}")
    log.success("Repair complete")


def cmd_version():
    print(__version__)


# ── main ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(f"{__app_name__} {__version__}")
        print(f"Repo: {__repo__}")
        print()
        print("Usage: python3 -m installer <command>")
        print()
        print("Commands:")
        print("  install    Bootstrap the environment")
        print("  update     Self-update the installer")
        print("  doctor     Run system diagnostics")
        print("  verify     Verify installed dependencies")
        print("  config     View configuration")
        print("  uninstall  Remove installed components")
        print("  logs       View installation logs")
        print("  status     Show installation status")
        print("  repair     Attempt repair")
        print("  version    Show version")
        return

    command = sys.argv[1]
    commands = {
        "install": cmd_install,
        "update": cmd_update,
        "doctor": cmd_doctor,
        "verify": cmd_verify,
        "config": cmd_config,
        "uninstall": cmd_uninstall,
        "logs": cmd_logs,
        "status": cmd_status,
        "repair": cmd_repair,
        "version": cmd_version,
    }
    if command in commands:
        commands[command]()
    else:
        log.error(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
