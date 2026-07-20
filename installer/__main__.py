import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer import __version__, __app_name__, __repo__
from installer.core.executor import run_command, check_command
from installer.core.config import InstallerConfig
from installer.interactive.ui import (
    heading, status, success, error, warn, prompt, confirm,
    choose, summary_box, colored, Color, Spinner,
)
from installer.logging.logger import init_logging, get_logger, get_log_file
from installer.platforms import detect_platform
from installer.verification.checker import Verifier

PROJECT_DIR = Path(__file__).resolve().parent.parent

def first_run_wizard(config: InstallerConfig, platform):
    """Interactive first-run setup — prompts for Supabase creds, preferences."""
    heading("First-Run Setup")

    status("No configuration found. Let's set up your VPLink environment.", "info")
    print()

    if not confirm("Configure Supabase credentials (required for proxy rotation)?", default=True):
        status("Skipping Supabase config — proxy rotation will be unavailable", "warn")
    else:
        status("Enter your Supabase project credentials from https://supabase.com", "info")
        print()

        supabase_url = prompt("Supabase Project URL", default=config.get("supabase_url", ""))
        if supabase_url:
            config.set("supabase_url", supabase_url)

        supabase_key = prompt("Supabase anon/public key", default=config.get("supabase_key", ""))
        if supabase_key:
            config.set("supabase_key", supabase_key)

        supabase_secret = prompt("Supabase service_role secret", default=config.get("supabase_secret", ""))
        if supabase_secret:
            config.set("supabase_secret", supabase_secret)

        status("Supabase credentials saved", "ok")

    proxy_choices = ["normal", "premium"]
    default_tier = config.get("proxy_tier", "premium")
    default_idx = proxy_choices.index(default_tier) if default_tier in proxy_choices else 1
    tier_idx = choose("Proxy tier?", proxy_choices, default=default_idx + 1)
    config.set("proxy_tier", proxy_choices[tier_idx])

    yt = confirm("Enable YouTube traffic (referral headers)?", default=config.get("youtube_traffic", True))
    config.set("youtube_traffic", yt)

    mob = confirm("Enable mobile profile (Android emulation)?", default=config.get("mobile_profile", True))
    config.set("mobile_profile", mob)

    views_str = prompt("Default views per run", default=str(config.get("views", 100)))
    try:
        config.set("views", int(views_str))
    except ValueError:
        config.set("views", 100)

    config.set("setup_complete", True)
    config.save()
    status("Configuration saved", "ok")


def cmd_install():
    heading(f"VPLink {__version__} Installer")

    log = get_logger("install")

    # ── Step 1: Platform detection ──
    with Spinner("Detecting platform"):
        platform = detect_platform()
    status(f"OS: {platform.name}/{platform.distribution} {platform.version}", "ok")
    status(f"Arch: {platform.arch}", "ok")
    status(f"Package manager: {platform.package_manager}", "ok")
    log.info(f"Platform: {platform.name} {platform.distribution} {platform.version} {platform.arch}")

    if platform.is_wsl:
        status("Running in WSL", "info")
    if platform.is_docker:
        status("Running in Docker", "info")

    # ── Step 2: Create config dirs ──
    config = InstallerConfig()
    config_dir = Path(config.config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "logs").mkdir(parents=True, exist_ok=True)
    (config_dir / "rollback").mkdir(parents=True, exist_ok=True)

    # Project results dir
    results_dir = PROJECT_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    status(f"Config directory: {config_dir}", "ok")

    # ── Step 3: First-run wizard ──
    if not config.get("setup_complete", False):
        first_run_wizard(config, platform)
    else:
        status("Configuration already set up", "ok")

    # ── Step 4: sudo check ──
    needs_sudo = platform.name in ("linux",) and not platform.is_wsl
    if needs_sudo:
        sudo_ok = check_command("sudo")
        if not sudo_ok:
            error("sudo is required but not available")
            error("Install sudo or run as root")
            sys.exit(1)

    use_sudo = needs_sudo

    # ── Step 5: Package index update ──
    if platform.package_manager in ("apt", "dnf", "pacman", "zypper", "brew", "pkg"):
        with Spinner("Updating package index"):
            from installer.platforms import get_platform
            plat_cls = get_platform()
            try:
                plat_cls.update_package_index(use_sudo)
            except Exception:
                pass
        status("Package index updated", "ok")

    # ── Step 6: Install system packages ──
    heading("Installing System Packages")

    from installer.packages.manager import PackageManager
    from installer.packages.definitions import PACKAGES
    pm = PackageManager()

    system_results = pm.install_many([
        pkg for pkg in PACKAGES if pkg.category in ("system", "tool", "runtime")
    ])

    # Browser packages — use fallback for chromium-browser snap issue
    browser_pkgs = [pkg for pkg in PACKAGES if pkg.category == "browser"]
    for pkg in browser_pkgs:
        if pkg.name == "chromium-browser":
            pm.install_chromium_with_fallback(use_sudo)
        else:
            pm.install(pkg, use_sudo)

    ok_count = sum(1 for v in system_results.values() if v)
    fail_count = sum(1 for v in system_results.values() if not v)
    if fail_count == 0:
        status("All system packages installed", "ok")
    else:
        warn(f"{ok_count}/{len(system_results)} installed ({fail_count} failed)")

    # ── Step 7: Python dependencies ──
    heading("Installing Python Dependencies")

    req_file = PROJECT_DIR / "requirements.txt"
    if req_file.exists():
        with Spinner("Installing pip packages"):
            result = run_command(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                timeout=120,
            )
        if result.success:
            status("Python dependencies installed", "ok")
        else:
            warn(f"pip install: {result.stderr[:200]}")

    # Ensure key runtime dependencies
    for pkg_name in ["selenium", "webdriver-manager", "requests"]:
        with Spinner(f"Installing {pkg_name}"):
            run_command(
                [sys.executable, "-m", "pip", "install", "--quiet", pkg_name],
                timeout=60,
            )
        status(f"{pkg_name} installed", "ok")

    # ── Step 8: Environment setup ──
    heading("Environment Setup")

    # Add project bin/scripts to PATH via shell profile
    from installer.config import profiles
    for profile_path in profiles.get_profile_paths(platform.shell, platform.home):
        if profile_path.exists() or confirm(f"Create {profile_path}?", default=True):
            modified, _ = profiles.ensure_marker(profile_path, __app_name__)
            if modified:
                profiles.add_path_entry(profile_path, str(PROJECT_DIR), __app_name__)
                status(f"Updated {profile_path.name}", "ok")
            else:
                status(f"{profile_path.name} already configured", "info")

    # ── Step 9: Verification ──
    heading("Verification")

    verifier = Verifier()
    check_results = verifier.check_all()
    verifier.print_report(check_results)

    summary = verifier.summary(check_results)

    # ── Step 10: Summary ──
    heading("Installation Complete")

    items = [
        ("Version", __version__, "info"),
        ("Platform", f"{platform.name}/{platform.distribution}", "info"),
        ("Architecture", platform.arch, "info"),
        ("Config", str(config_dir), "info"),
        ("Packages", f"{summary['installed']}/{summary['total']}", "ok" if summary['all_ok'] else "warn"),
    ]
    summary_box("VPLink 3.0", items)

    if summary["all_ok"]:
        success("All systems ready")
        print()
        print(colored("  Next steps:", Color.BOLD))
        print(f"    {colored('1.', Color.CYAN)} Run the funnel:  {colored('python3 automation.py <key>', Color.BOLD)}")
        print(f"    {colored('2.', Color.CYAN)} Interactive mode: {colored('bash vplink3.0.sh', Color.BOLD)}")
        print(f"    {colored('3.', Color.CYAN)} Desktop mode:     {colored('bash vplink-desktop.sh', Color.BOLD)}")
        print(f"    {colored('4.', Color.CYAN)} Re-run installer: {colored('python3 -m installer install', Color.BOLD)}")
        print()
    else:
        warn(f"{summary['missing']} package(s) need attention. Run {colored('python3 -m installer verify', Color.BOLD)}")


def cmd_update():
    from installer.update.self_update import do_update
    do_update()


def cmd_verify():
    verifier = Verifier()
    results = verifier.check_all()
    verifier.print_report(results)


def cmd_doctor():
    heading("System Doctor")

    platform = detect_platform()
    status(f"OS: {platform.name} {platform.distribution} {platform.version}", "ok")
    status(f"Arch: {platform.arch}", "ok")
    status(f"Package Manager: {platform.package_manager}", "ok")
    status(f"Shell: {platform.shell}", "ok")
    status(f"Config: {platform.config_dir}", "ok")

    if platform.is_wsl:
        status("Running in WSL", "info")
    if platform.is_docker:
        status("Running in Docker", "info")

    verifier = Verifier()
    results = verifier.check_all()
    verifier.print_report(results)


def cmd_config():
    config = InstallerConfig()

    if len(sys.argv) < 3:
        print(f"Usage: python3 -m installer config <action> [key] [value]")
        print()
        print("Actions:")
        print("  list              Show all config")
        print("  get <key>         Get a config value")
        print("  set <key> <val>   Set a config value")
        print("  setup             Run first-time configuration wizard")
        return

    action = sys.argv[2]

    if action == "list":
        print(json.dumps(config.as_dict(), indent=2))

    elif action == "get" and len(sys.argv) >= 4:
        val = config.get(sys.argv[3])
        print(val if val is not None else "(not set)")

    elif action == "set" and len(sys.argv) >= 5:
        config.set(sys.argv[3], sys.argv[4])
        config.save()
        status(f"Set {sys.argv[3]} = {sys.argv[4]}", "ok")

    elif action == "setup":
        from installer.platforms import detect_platform
        platform = detect_platform()
        first_run_wizard(config, platform)

    else:
        warn("Invalid config command")


def cmd_uninstall():
    heading("Uninstall VPLink 3.0")

    if not confirm("Remove all VPLink files and configuration?", default=False):
        status("Uninstall cancelled", "info")
        return

    from installer.config import profiles
    platform = detect_platform()

    for profile_path in profiles.get_profile_paths(platform.shell, platform.home):
        if profile_path.exists():
            profiles.remove_section(profile_path)
            status(f"Cleaned {profile_path.name}", "ok")

    config_dir = Path(platform.config_dir)
    if config_dir.exists():
        import shutil
        shutil.rmtree(str(config_dir))
        status(f"Removed {config_dir}", "ok")

    status("Uninstall complete", "ok")
    warn("Project files (automation.py, results/) were preserved")


def cmd_logs():
    log_file = get_log_file()
    if log_file and log_file.exists():
        print(log_file.read_text(encoding="utf-8", errors="ignore"))
        return

    log_dir = Path.home() / ".config" / "vplink3" / "logs"
    if log_dir.exists():
        logs = sorted(log_dir.glob("*.log"), reverse=True)
        if logs:
            print(logs[0].read_text(encoding="utf-8", errors="ignore"))
            return
    warn("No logs found")


def cmd_status():
    heading("VPLink 3.0 Status")

    platform = detect_platform()
    status(f"Version: {__version__}", "info")
    status(f"Platform: {platform.name} {platform.arch}", "info")
    status(f"Config: {platform.config_dir}", "info")

    verifier = Verifier()
    results = verifier.check_all()

    for r in results:
        icon = colored("✓", Color.GREEN) if r.installed else colored("✗", Color.RED)
        version = f" ({r.version})" if r.version else ""
        print(f"  {icon} {r.display_name}{version}")

    print()
    summary = verifier.summary(results)
    if summary["all_ok"]:
        success("All systems operational")
    else:
        warn(f"{summary['missing']} package(s) need attention")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(f"VPLink {__version__} — Cross-Platform Bootstrap Installer")
        print()
        print(f"Repo: {__repo__}")
        print()
        print("Usage: python3 -m installer <command>")
        print()
        print("Commands:")
        print("  install    One-time setup: installs everything needed")
        print("  update     Self-update the installer")
        print("  verify     Verify installation")
        print("  doctor     System health diagnostics")
        print("  config     Manage configuration")
        print("  uninstall  Remove VPLink configuration")
        print("  logs       Show installation logs")
        print("  status     Show installation status")
        print("  version    Show version")
        return

    init_logging()

    command = sys.argv[1]
    commands = {
        "install": cmd_install,
        "update": cmd_update,
        "verify": cmd_verify,
        "doctor": cmd_doctor,
        "config": cmd_config,
        "uninstall": cmd_uninstall,
        "logs": cmd_logs,
        "status": cmd_status,
        "version": lambda: print(__version__),
    }

    if command in commands:
        commands[command]()
    else:
        error(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
