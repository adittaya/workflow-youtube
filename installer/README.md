# ⚡ Installer

**Production-Grade Cross-Platform Bootstrap Installer**

A modular, extensible, fault-tolerant installer that automatically installs, configures, and verifies development environments on Linux, macOS, Windows, and Termux.

## Features

- **Cross-Platform**: Ubuntu, Debian, Fedora, Arch, openSUSE, macOS, Windows, Termux
- **Automatic Detection**: OS, distro, arch, shell, package manager, root, WSL, Docker
- **Package Abstraction**: Same API works with apt, dnf, pacman, brew, winget, pkg
- **Interactive TUI**: React-powered terminal UI (OpenTUI — no FPS cap, Zig renderer)
- **Progress Display**: Real-time installation progress with colored output
- **Dependency Detection**: Skips installed packages, upgrades outdated
- **Environment Setup**: PATH, env vars, shell profiles (.bashrc, .zshrc, fish)
- **Download Manager**: GitHub releases, archives, SHA256 verification, retry
- **Rollback**: Automatic rollback on failure
- **Logging**: Detailed logs with timestamps and context
- **Verification**: Post-install checks for all packages
- **Self-Update**: Check and install updates from GitHub releases
- **Doctor Mode**: Diagnose system issues

## Quick Start

```bash
# Interactive TUI
bun run src/cli.tsx

# Install default packages
bun run src/cli.tsx install

# Install specific packages
bun run src/cli.tsx install git nodejs python3

# Diagnose system
bun run src/cli.tsx doctor

# Verify installations
bun run src/cli.tsx verify

# Build standalone binary
bun build src/cli.tsx --compile --outfile installer
```

## Commands

| Command | Description |
|---------|-------------|
| `installer` | Launch interactive TUI |
| `installer install [pkgs]` | Install packages |
| `installer update` | Check for self-updates |
| `installer repair` | Re-run installation to fix issues |
| `installer doctor` | Diagnose system and show issues |
| `installer verify` | Verify all installed packages |
| `installer config` | Show current configuration |
| `installer uninstall [--config]` | Remove installed packages |
| `installer logs` | Show installer logs |
| `installer version` | Show version |
| `installer status` | Show package status |
| `installer platform` | Show platform information |

## Architecture

```
installer/
├── src/
│   ├── core/                    # Core modules
│   │   ├── types.ts             # TypeScript type definitions
│   │   ├── platform.ts          # OS/arch/package manager detection
│   │   ├── package-manager.ts   # Package manager abstraction
│   │   ├── environment.ts       # PATH and env var management
│   │   ├── downloader.ts        # Download with retry/SHA256
│   │   ├── config.ts            # Configuration management
│   │   ├── logger.ts            # Structured logging
│   │   ├── rollback.ts          # Transaction-like rollback
│   │   ├── verification.ts      # Post-install verification
│   │   ├── update.ts            # Self-update mechanism
│   │   └── installer.ts         # Main installer engine
│   ├── packages/
│   │   └── definitions.ts       # Package registry (19 packages)
│   ├── interactive/
│   │   ├── components.tsx       # TUI components (Header, Progress, etc.)
│   │   └── app.tsx              # Main TUI application
│   ├── cli.tsx                  # CLI entry point
│   └── index.ts                 # Library exports
├── tests/
│   └── platform.test.ts         # Unit tests
├── .github/workflows/
│   ├── ci.yml                   # CI pipeline
│   └── release.yml              # Release workflow
├── package.json
└── tsconfig.json
```

## Platform Support

| Platform | Package Manager | Status |
|----------|----------------|--------|
| Ubuntu | apt | ✅ Full |
| Debian | apt | ✅ Full |
| Fedora | dnf | ✅ Full |
| Arch Linux | pacman | ✅ Full |
| openSUSE | zypper | ✅ Full |
| macOS | brew | ✅ Full |
| Windows | winget | ✅ Full |
| Termux | pkg | ✅ Full |

## Package Registry

19 packages across 7 categories:

- **Core**: git, curl, wget, unzip
- **Languages**: Node.js, Python, Java, Rust, Go, Ruby, Bun
- **Dev Tools**: build-essential, gcc, make
- **Containers**: Docker
- **Editors**: VS Code, Vim
- **CLI Tools**: htop, tmux, jq, tree, GitHub CLI

## Configuration

Config stored in `~/.config/installer/config.json`:

```json
{
  "version": "1.0.0",
  "installDir": "~/.local/bin",
  "packages": ["git", "curl", "nodejs", "python3"],
  "envVars": {},
  "PATH": ["~/.local/bin"]
}
```

## Development

```bash
# Install dependencies
npm install

# Run in development mode
bun run dev

# Run tests
bun test

# Type check
bun run lint

# Build binary
bun run build
```

## License

MIT
