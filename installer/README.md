# yt-auto Bootstrap Installer

A production-grade, cross-platform bootstrap installer for the **yt-auto**
YouTube upload automation tool. One command installs every system package,
Python tool, the project source, a global `yt-auto` command, the `YOUTUBE`
interactive TUI command, configuration, and a self-updating `installer` CLI —
on Linux, macOS, Windows and Termux.

It installs *an environment*, not a single binary: it detects the OS/distro/
architecture/shell/package manager, installs missing packages through a unified
abstraction (`install_package("git")` → `apt`/`dnf`/`pacman`/`zypper`/`brew`/
`winget`/`pkg`), downloads and verifies assets (SHA-256, size, resume, retry),
edits shell profiles idempotently, logs everything, verifies the result, and
can roll back a failed install.

## Quick start

Requires only **Python 3.10+** and a package manager.

```bash
# from a repo clone
python3 -m installer

# or the one-line bootstrap (no clone needed; fetches latest from GitHub)
bash <(curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-youtube/main/bootstrap.sh)

# or install the global command first, then drive it
python3 installer/bin/installer        # POSIX dev shim
installer install
installer doctor --fix
installer verify
```

Windows users: `powershell -ExecutionPolicy Bypass -File installer\windows\install.ps1`
(bootstraps Python + Winget first).

Termux users: the same `installer install` runs against `pkg` with no root.

## Commands

```
installer install     bootstrap the full environment (default; --dry-run plans only)
installer update      self-update from GitHub Releases (version compare + changelog)
installer repair      re-run failed/incomplete install stages
installer doctor      diagnose environment + install (--fix auto-applies safe fixes)
installer verify      check tools and the install; prints a status table
installer config      show / set configuration (JSON, YAML or TOML)
installer uninstall   remove install + PATH edits (keeps ~/.yt-mirror data)
installer logs        show the installer log
installer version     print the installer version
installer status      environment + installation summary
```

All commands support `--non-interactive` (safe for CI) and `-v` (verbose logs).

## What it does

1. **Detect** — OS, distro, arch, shell, package manager, privileges, WSL,
   Docker, existing software (with versions).
2. **Verify prerequisites** — Python >= 3.10, a supported package manager.
3. **Install packages** — logical names (`git`, `python`, `ffmpeg`, `yt-dlp`)
   mapped per platform. Already-installed tools are skipped; `upgrade: true`
   upgrades them.
4. **Install source** — copies the project (or clones it) to the platform data
   directory.
5. **Install Python deps** — `requirements.txt` with pip fallbacks.
6. **Configure** — platform-standard config dir
   (`~/.config/installer/` · `%APPDATA%\installer\` · `~/.config/installer/`),
   `~/.yt-mirror` data layout, env vars.
7. **Global commands** — `installer`, `yt-auto` and `YOUTUBE` (interactive
   TUI) in `~/.local/bin` (POSIX) with PATH added to your shell profile
   (never twice).
8. **Verify** — table of Installed/Version/Status/Missing.
9. **Log & roll back** — every step is logged; a failed critical step undoes
   completed actions via the rollback journal.

## Package abstraction

`installer/packages.yaml` maps logical tools to per-manager names. Adding a
tool is a YAML entry — no code. Optional tools (`nodejs`, `docker`,
`chromium`, `vscode`…) are reported but never block an install.

```yaml
packages:
  ffmpeg:
    description: Video and audio processing engine
    verify: ffmpeg
    min_version: "4.0"
    systems:
      apt: [ffmpeg]
      dnf: [ffmpeg-free]
      pacman: [ffmpeg]
      zypper: [ffmpeg]
      brew: [ffmpeg]
      pkg: [ffmpeg]
      winget: [Gyan.FFmpeg]
```

## Layout

```
installer/
  cli.py               subcommand CLI
  operations.py        staged install pipeline
  core/                env, packages, config, state, shellprofile, logging, utils
  platforms/           apt / dnf / pacman / zypper / brew / pkg / winget backends
  downloads.py         SHA-256 / size / resume / retry downloads + archive extraction
  interactive.py       welcome screen, progress, menus, spinner, prompts
  verification.py      tool + install checks
  doctor.py            diagnostics with safe auto-fixes
  update.py            GitHub Releases self-update
  rollback.py          undo journal
  uninstall.py         clean removal
  packages.yaml        package definitions
  windows/install.ps1  Windows bootstrap
  docs/                architecture, install, config, testing guides
  tests/               stdlib unittest suite (python3 installer/tests/run_tests.py)
```

## Configuration

Defaults are sane; the file lives in the platform config dir:

```bash
installer config show                 # print current configuration
installer config set shell_profile no # change a setting
installer config env YT_COOKIES ...   # add an env var (added to profiles on next install)
```

See [docs/configuration.md](docs/configuration.md) for all keys.

## Documentation

- [Architecture](docs/architecture.md) — module map + sequence diagram
- [Installation guide](docs/installation.md) — per-platform steps
- [Configuration guide](docs/configuration.md) — every config key
- [Package definitions](docs/packages.md) — how to add tools
- [Testing](docs/testing.md) — running the test suite

## Development

```bash
python3 installer/tests/run_tests.py   # 50+ unit/integration tests
python3 -m py_compile installer/**/*.py
```
