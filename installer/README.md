# VPLink 3.0 Installer

Production-grade, cross-platform bootstrap installer for VPLink 3.0.

## Features

- **Cross-platform**: Linux (Ubuntu, Debian, Fedora, Arch, openSUSE, Alpine), macOS, Windows, Termux
- **Automatic detection**: OS, distro, architecture, package manager, Docker, WSL, CI
- **Modular architecture**: 26 source files, 10,000+ lines, clean separation of concerns
- **Idempotent**: Safe to run multiple times, skips completed steps
- **Rollback support**: Automatic rollback on failure
- **Interactive UI**: Progress bars, spinners, colored output, menus
- **Package abstraction**: Install packages regardless of OS/package manager
- **Download manager**: SHA256 verification, retry, resume
- **Self-healing**: `doctor` command diagnoses issues, `repair` fixes them
- **76 tests**: Unit + integration tests, CI/CD via GitHub Actions

## Quick Start

```bash
# One-command install
curl -fsSL https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/installer/installer.sh | bash

# Or clone and run locally
git clone https://github.com/adittaya/VPLINK-3.0.git
cd VPLINK-3.0
bash installer/installer.sh install
```

## Commands

| Command | Description |
|---------|-------------|
| `installer install` | Full installation |
| `installer update` | Update to latest version |
| `installer repair` | Fix broken installation |
| `installer uninstall` | Remove installation |
| `installer doctor` | System diagnostics |
| `installer verify` | Verify installation integrity |
| `installer config list` | Show configuration |
| `installer config get <key>` | Get config value |
| `installer config set <key> <value>` | Set config value |
| `installer logs` | View installation logs |
| `installer status` | Show component status |
| `installer version` | Show version info |
| `installer help` | Show help |

## Options

| Flag | Description |
|------|-------------|
| `-n, --noninteractive` | Skip prompts (use defaults) |
| `-d, --debug` | Enable debug output |
| `--dry-run` | Simulate without changes |
| `-f, --force` | Skip confirmations |

## Architecture

```
installer/
├── installer.sh              # Main entry point (461 lines)
├── core/                     # Core modules
│   ├── platform.sh           # OS/distro/arch detection (592 lines)
│   ├── packages.sh           # Package abstraction layer (598 lines)
│   ├── logger.sh             # Logging system (236 lines)
│   ├── state.sh              # State management (250 lines)
│   ├── config.sh             # Configuration management (258 lines)
│   ├── download.sh           # Download manager (393 lines)
│   ├── env.sh                # Environment/PATH management (346 lines)
│   └── rollback.sh           # Rollback system (222 lines)
├── platforms/                # Platform-specific modules
│   ├── linux.sh              # Linux (debian/fedora/arch/suse/alpine) (784 lines)
│   ├── macos.sh              # macOS (415 lines)
│   ├── windows.sh            # Windows/PowerShell (634 lines)
│   └── termux.sh             # Termux/Android (529 lines)
├── commands/                 # CLI commands
│   ├── install.sh            # Install command (497 lines)
│   ├── update.sh             # Update command (159 lines)
│   ├── repair.sh             # Repair command (321 lines)
│   ├── uninstall.sh          # Uninstall command (185 lines)
│   ├── status.sh             # Status command (232 lines)
│   ├── config.sh             # Config command (365 lines)
│   └── logs.sh               # Logs command (126 lines)
├── verification/             # Verification & diagnostics
│   ├── verify.sh             # Post-install verification (227 lines)
│   └── doctor.sh             # System diagnostics (279 lines)
├── interactive/              # Terminal UI
│   └── ui.sh                 # Colors, progress, menus, spinners (748 lines)
├── packages/                 # Package definitions
│   └── definitions.sh        # Cross-platform package mappings (295 lines)
├── tests/                    # Tests
│   ├── test_core.sh          # Unit tests (606 lines)
│   └── test_integration.sh   # Integration tests (494 lines)
└── docs/                     # Documentation (future)
```

**Total: 26 files, 10,252 lines of bash**

## Supported Platforms

| Platform | Distro | Package Manager | Status |
|----------|--------|----------------|--------|
| Linux | Ubuntu, Debian, Kali, Mint | apt-get | ✓ |
| Linux | Fedora, CentOS, Rocky, Alma | dnf/yum | ✓ |
| Linux | Arch, Manjaro, EndeavourOS | pacman | ✓ |
| Linux | openSUSE, SUSE | zypper | ✓ |
| Linux | Alpine | apk | ✓ |
| macOS | Intel & Apple Silicon | brew | ✓ |
| Windows | Git Bash, MSYS2, WSL | winget/choco | ✓ |
| Android | Termux | pkg | ✓ |

## Package Abstraction

The installer maps generic package names to platform-specific packages:

| Generic | Debian | Fedora | Arch | macOS | Termux |
|---------|--------|--------|------|-------|--------|
| git | git | git | git | git | git |
| chromium | chromium-browser | chromium | chromium | --cask chromium | chromium |
| xvfb | xvfb | xorg-x11-server-Xvfb | xorg-server-xvfb | -- | xvfb |
| jq | jq | jq | jq | jq | jq |
| node | nodejs | nodejs | nodejs | node | nodejs-lts |

## Testing

```bash
# Run unit tests
bash installer/tests/test_core.sh

# Run integration tests
bash installer/tests/test_integration.sh

# Lint with shellcheck
shellcheck -S warning installer/**/*.sh installer/*.sh
```

## CI/CD

- **installer-ci.yml**: Runs on push/PR — lint, test (Linux, macOS, Termux), smoke test
- **installer-release.yml**: Runs on tag push — validate, build, create GitHub Release with checksums

## Configuration

Config stored at `~/.config/installer/config.json` (Linux/macOS) or `%APPDATA%/installer/config.json` (Windows).

State stored at `~/.config/installer/state.json` — tracks which installation steps completed.

## License

MIT
