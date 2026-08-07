"""The ``installer`` command-line interface.

Commands:
  install   bootstrap the full environment (default)
  fix       all-in-one self-heal: diagnose+fix, repair install, verify
  update    self-update from GitHub Releases
  repair    re-run failed/incomplete install stages
  doctor    diagnose the environment (with --fix)
  verify    check installed tools and the install itself
  config    show/set configuration
  uninstall remove the installation (keeps user data unless --purge)
  logs      show the installer log
  version   print the installer version
  status    environment + installation summary
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from installer.core import env
from installer.interactive import UI
from installer.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="installer",
        description="Bootstrap installer for the yt-auto video automation tool.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose debug logging")
    parser.add_argument("--non-interactive", action="store_true",
                        help="never prompt; use defaults (safe for CI)")
    sub = parser.add_subparsers(dest="command", metavar="command")

    install = sub.add_parser("install", help="bootstrap the full environment (default)")
    install.add_argument("--dry-run", action="store_true",
                         help="plan the install without changing the system")
    sub.add_parser("fix", help="all-in-one self-heal (doctor --fix + repair + verify)")
    sub.add_parser("update", help="self-update from GitHub Releases")
    sub.add_parser("repair", help="re-run failed/incomplete install stages")

    doctor = sub.add_parser("doctor", help="diagnose environment + install")
    doctor.add_argument("--fix", action="store_true", help="auto-apply safe fixes")

    sub.add_parser("verify", help="check installed tools and the install")

    cfg = sub.add_parser("config", help="show or set configuration")
    cfg.add_argument("action", nargs="?", choices=["show", "set", "env"], default="show")
    cfg.add_argument("key", nargs="?", help="key for set/env")
    cfg.add_argument("value", nargs="?", help="value for set/env")

    uninstall = sub.add_parser("uninstall", help="remove the installation")
    uninstall.add_argument("--remove-config", action="store_true",
                           help="also delete installer config")
    uninstall.add_argument("--purge", action="store_true",
                           help="also delete ~/.yt-mirror user data (after confirm)")

    logs = sub.add_parser("logs", help="show the installer log")
    logs.add_argument("lines", nargs="?", type=int, default=60)

    sub.add_parser("version", help="print version")
    sub.add_parser("status", help="environment + installation summary")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # Logging + UI configured consistently for every command.
    from installer.core.logging import configure_logger

    configure_logger(verbose=args.verbose, console=True)
    ui = UI(non_interactive=args.non_interactive)

    from installer import operations

    if args.command in (None, "install"):
        return operations.run_install(ui, operations.load_config(),
                                      non_interactive=args.non_interactive,
                                      dry_run=getattr(args, "dry_run", False))
    if args.command == "update":
        return operations.run_update(ui, operations.load_config())
    if args.command == "fix":
        return operations.run_fix(ui, operations.load_config())
    if args.command == "repair":
        return operations.run_repair(ui, operations.load_config())
    if args.command == "doctor":
        return operations.run_doctor(ui, operations.load_config(), auto_fix=args.fix)
    if args.command == "verify":
        return operations.run_verify(ui, operations.load_config())
    if args.command == "status":
        return operations.run_status(ui, operations.load_config())
    if args.command == "logs":
        return operations.run_logs(ui, args.lines)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "config":
        return run_config(ui, args)
    if args.command == "uninstall":
        return operations.run_uninstall(ui, operations.load_config(),
                                        remove_config=args.remove_config,
                                        purge_data=args.purge)
    return 0


def run_config(ui, args) -> int:
    from installer import operations

    config = operations.load_config()
    if args.action == "show":
        import json

        ui.title("Configuration")
        print(json.dumps(config.to_dict(), indent=2, sort_keys=True))
        print()
        ui.dim(f"file: {env.config_home('installer') / 'config.json'}")
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            ui.error("usage: installer config set <key> <value>")
            return 2
        if args.key in ("install_dir", "data_dir", "mirror_home"):
            from pathlib import Path

            config.set(args.key, str(Path(args.value).expanduser()))
        else:
            config.set(args.key, args.value)
        operations.save_config(config)
        ui.ok(f"set {args.key}")
        return 0
    if args.action == "env":
        if not args.key or args.value is None:
            ui.error("usage: installer config env <KEY> <VALUE>")
            return 2
        env_cfg = config.to_dict().setdefault("env", {})
        env_cfg[args.key] = args.value
        config.set("env", env_cfg)
        operations.save_config(config)
        ui.ok(f"env {args.key} configured (added to shell profile on next install)")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
