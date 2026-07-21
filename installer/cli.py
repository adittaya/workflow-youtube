#!/usr/bin/env python3
"""
VPLink 24/7 — Production-Grade Cross-Platform Bootstrap Installer

Usage:
  installer install       Install/update all configured packages
  installer update        Self-update the installer
  installer doctor        Run system diagnostics
  installer verify        Verify installed dependencies
  installer config        View/edit configuration
  installer uninstall     Remove installed components
  installer logs          View installation logs
  installer status        Show installation status
  installer version       Show version
  installer repair        Attempt to repair installation
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer.core.platform import detect, is_supported, suggest_install
from installer.platforms import get_platform
from installer.packages import register_packages, is_installed
from installer.config import Config, ensure_dirs
from installer.config.profiles import add_path, add_env
from installer.downloads import download, validate_url, make_executable
from installer.rollback import RollbackManager, FileBackup
from installer.verification import verify_all, doctor, print_doctor_report
from installer.update import get_current_version, check_latest, update_self, compare_versions, get_changelog
from installer.interactive import welcome, confirm, choose, input_text, header, Spinner, ProgressBar
from installer import logging as log

VERSION = get_current_version()
LOG_DIR = str(Path.home() / ".config" / "vplink" / "logs")


def cmd_install():
    """Main install command — bootstrap the environment."""
    log.init(LOG_DIR, level="info")

    info = detect()

    if not is_supported():
        log.error(f"Unsupported platform: {info.os_name}/{info.distribution}")
        sys.exit(1)

    welcome()
    log.info(f"Platform: {info.os_name}/{info.distribution} ({info.arch})")
    log.info(f"Shell: {info.shell} | Package Manager: {info.package_manager}")
    if not info.package_manager:
        manager = suggest_install()
        log.warn(f"No package manager detected. Try: {manager}")
    log.info(f"Logging to: {LOG_DIR}")
    print()

    # ── Step 1: Update package DB ──
    log.header("Step 1: Updating Package Database")
    platform = get_platform(info)
    if info.package_manager:
        with Spinner("Updating package database..."):
            ok = platform.update_package_db()
        if not ok:
            log.warn("Package DB update skipped or failed")
    else:
        log.warn("No package manager — skipping update")

    # ── Step 2: Install packages ──
    log.header("Step 2: Installing Required Packages")
    register_packages()
    packages = ["git", "curl", "wget", "python3"]
    for pkg in packages:
        installed, version = is_installed(pkg)
        if installed:
            log.success(f"{pkg}: {version or 'already installed'}")
        else:
            with Spinner(f"Installing {pkg}..."):
                result = platform.install_package(pkg)
            if result.success:
                log.success(f"{pkg}: {result.version or 'installed'}")
            else:
                log.error(f"{pkg}: {result.error or 'install failed'}")
                if not confirm("Continue despite error?"):
                    sys.exit(1)

    # ── Step 3: Python packages ──
    log.header("Step 3: Installing Python Packages")
    py_packages = ["flask", "pynacl", "requests", "selenium"]
    for pkg in py_packages:
        with Spinner(f"Installing {pkg}..."):
            result = platform.install_package(pkg)
        if result.success:
            log.success(f"{pkg}: {result.version or 'installed'}")
        else:
            log.warn(f"{pkg}: {result.error or 'install issue'}")

    # ── Step 4: Environment Setup ──
    log.header("Step 4: Configuring Environment")
    ensure_dirs(info)
    config = Config("vplink", info)
    cfg = config.load()

    bin_dir = info.bin_dir
    if info.os_name != "windows":
        Path(bin_dir).mkdir(parents=True, exist_ok=True)
        add_path(info, bin_dir)

    # Set up the vplink247 command
    manager_dir = Path(__file__).parent.parent / "manager"
    if (manager_dir / "install.sh").exists():
        with Spinner("Setting up global command..."):
            try:
                subprocess.run(["sudo", "cp", str(manager_dir / "install.sh"),
                                "/usr/local/bin/vplink247"], capture_output=True)
                subprocess.run(["sudo", "chmod", "+x", "/usr/local/bin/vplink247"],
                               capture_output=True)
                log.success("Global command: vplink247")
            except Exception as e:
                log.warn(f"Could not install global command: {e}")

    # ── Step 5: Configuration ──
    log.header("Step 5: First-Run Configuration")

    if not cfg.get("supabase_url"):
        log.info("Let's configure Supabase (needed for proxy rotation):")
        supabase_url = input_text("Supabase URL", "https://")
        supabase_key = input_text("Supabase Anon Key")
        supabase_secret = input_text("Supabase Service Role Key", secret=True)

        if supabase_url and supabase_key and supabase_secret:
            config.set("supabase_url", supabase_url)
            config.set("supabase_key", supabase_key)
            config.set("supabase_secret", supabase_secret)
            add_env(info, "SUPABASE_URL", supabase_url)
            add_env(info, "SUPABASE_KEY", supabase_key)
            add_env(info, "SUPABASE_SECRET", supabase_secret)
            log.success("Supabase configured")

    # ── Step 6: Verification ──
    log.header("Step 6: Verifying Installation")
    verify_result = verify_all()
    for c in verify_result:
        if c["ok"]:
            log.success(f"{c['name']}: {c['version'] or 'ok'}")
        else:
            log.error(f"{c['name']}: missing")

    # ── Done ──
    print()
    log.header("Installation Complete!")
    log.success("VPLink 24/7 environment is ready")
    print()
    print(f"  Next steps:")
    print(f"    • Run:  vplink247              — Terminal mode")
    print(f"    • Run:  vplink247 web          — Web interface")
    print(f"    • Run:  installer doctor       — Diagnostics")
    print(f"    • Run:  installer logs         — View logs")
    print()


def cmd_update():
    """Self-update the installer."""
    log.init(LOG_DIR)
    header("Updating VPLink Installer")
    latest = check_latest()
    if latest and compare_versions(latest, VERSION) > 0:
        log.info(f"New version available: {latest}")
        changelog = get_changelog(latest)[:500]
        if changelog:
            print(f"  Changelog:")
            for line in changelog.split("\n")[:10]:
                print(f"    {line}")
        if confirm("Update now?"):
            if update_self():
                log.success(f"Updated to {latest}")
                log.info("Please restart: installer doctor")
            else:
                log.error("Update failed")
    else:
        log.success(f"You're up to date ({VERSION})")


def cmd_doctor():
    """Run diagnostics and print system health report."""
    log.init(LOG_DIR)
    info = detect()
    report = doctor(info)
    print_doctor_report(report)
    print()
    if report["summary"]["critical_failed"] > 0:
        log.warn("Critical dependencies missing. Run: installer install")
    else:
        log.success("System healthy!")


def cmd_verify():
    """Verify installed dependencies."""
    log.init(LOG_DIR)
    header("Dependency Verification")
    verify_result = verify_all()
    all_ok = True
    for c in verify_result:
        if c["ok"]:
            log.success(f"{c['name']}: {c['version'] or 'present'}")
        else:
            log.error(f"{c['name']}: NOT FOUND")
            all_ok = False
    print()
    if all_ok:
        log.success("All dependencies verified")
    else:
        log.warn("Some dependencies are missing. Run: installer install")


def cmd_config():
    """View/edit configuration."""
    info = detect()
    config = Config("vplink", info)
    cfg = config.load()

    header("Configuration")
    if not cfg:
        log.info("No configuration found")
        return

    print(f"  Config file: {config.path()}")
    print()
    for k, v in cfg.items():
        if any(s in k.lower() for s in ["secret", "token", "key", "password"]):
            v = v[:8] + "..." if len(v) > 20 else "***"
        print(f"  {k}: {v}")
    print()
    log.info(f"Config path: {config.path()}")
    log.info(f"Log path: {LOG_DIR}")


def cmd_uninstall():
    """Uninstall VPLink components."""
    header("Uninstall")
    if not confirm("Remove all VPLink configuration and data?", default=False):
        log.info("Uninstall cancelled")
        return

    config_dir = Path.home() / ".config" / "vplink"
    data_dir = Path.home() / ".local" / "share" / "vplink"

    if config_dir.exists():
        shutil.rmtree(config_dir)
        log.success("Removed config directory")
    if data_dir.exists():
        shutil.rmtree(data_dir)
        log.success("Removed data directory")

    # Remove global command
    for cmd_path in ["/usr/local/bin/vplink247", "/usr/local/bin/installer"]:
        if Path(cmd_path).exists():
            try:
                Path(cmd_path).unlink()
                log.success(f"Removed: {cmd_path}")
            except Exception as e:
                log.warn(f"Could not remove {cmd_path}: {e}")

    log.success("Uninstall complete")


def cmd_logs():
    """View installation logs."""
    log_dir = Path(LOG_DIR)
    if not log_dir.exists():
        log.error("No logs found")
        return

    logs = sorted(log_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        log.error("No logs found")
        return

    header(f"Recent Logs ({len(logs)} files)")
    for lp in logs[:10]:
        size = lp.stat().st_size
        mtime = time.ctime(lp.stat().st_mtime)
        print(f"  {mtime}  {size:>8}  {lp.name}")
    print()
    if logs:
        latest = logs[0]
        if confirm(f"View latest: {latest.name}?"):
            print()
            print(latest.read_text())


def cmd_status():
    """Show installation status."""
    info = detect()
    header("Installation Status")
    print(f"  Version:   {VERSION}")
    print(f"  Platform:  {info.os_name}/{info.distribution} ({info.arch})")
    print(f"  Shell:     {info.shell}")
    print(f"  Home:      {info.home}")
    print(f"  Config:    {info.config_dir}")
    print(f"  Data:      {info.data_dir}")
    print()

    register_packages()
    deps = ["git", "python3", "node", "docker", "curl", "wget"]
    for dep in deps:
        installed, version = is_installed(dep)
        status = f"✓ {version}" if installed else "✗ missing"
        color = "\033[32m" if installed else "\033[31m"
        print(f"  {color}{status}\033[0m  {dep}")

    config = Config("vplink", info)
    cfg = config.load()
    print()
    log.info(f"Config: {config.path()}")
    if cfg:
        log.success("Configured")
    else:
        log.warn("Not configured")


def cmd_repair():
    """Attempt to repair the installation."""
    log.init(LOG_DIR)
    header("Repair Mode")

    info = detect()
    platform = get_platform(info)

    verify_result = verify_all()
    missing = [c for c in verify_result if not c["ok"]]

    if not missing:
        log.success("Everything looks good — nothing to repair")
        return

    log.warn(f"Found {len(missing)} missing/repaired dependencies")
    for c in missing:
        with Spinner(f"Installing {c['name']}..."):
            result = platform.install_package(c["package"])
        if result.success:
            log.success(f"{c['name']}: installed")
        else:
            log.error(f"{c['name']}: {result.error or 'failed'}")

    log.success("Repair complete")


def main():
    if len(sys.argv) < 2:
        welcome()
        print(f"  Version {VERSION}")
        print()
        print(f"  Usage: installer <command>")
        print()
        print(f"  Commands:")
        print(f"    install     Bootstrap the environment")
        print(f"    update      Self-update the installer")
        print(f"    doctor      Run system diagnostics")
        print(f"    verify      Verify installed dependencies")
        print(f"    config      View configuration")
        print(f"    uninstall   Remove installed components")
        print(f"    logs        View installation logs")
        print(f"    status      Show installation status")
        print(f"    repair      Attempt repair")
        print(f"    version     Show version")
        print()
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
        "version": lambda: print(VERSION),
    }

    if command in commands:
        commands[command]()
    else:
        print(f"Unknown command: {command}")
        print(f"Run 'installer' without arguments to see usage")
        sys.exit(1)


if __name__ == "__main__":
    main()
