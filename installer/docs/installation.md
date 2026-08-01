# Installation guide

The installer needs only **Python 3.10+** and a working package manager. It
will install everything else.

## From a clone (all platforms)

```bash
git clone https://github.com/adittaya/workflow-youtube.git
cd workflow-youtube
python3 -m installer
```

`python3 -m installer install` is the default. Use `--dry-run` to see the plan
without changing anything.

## Linux (Ubuntu / Debian / Fedora / Arch / openSUSE)

```bash
python3 -m installer                  # detects apt/dnf/pacman/zypper
python3 -m installer doctor --fix     # fix anything the installer missed
```

- Debian/Ubuntu: `apt-get install -y python3` if Python is missing.
- Fedora/RHEL-family: `dnf install -y python3 python3-pip`.
- Arch: `pacman -S python python-pip`.
- openSUSE: `zypper install python3 python3-pip`.

Privileged installs are run with `sudo` automatically (only when required);
in non-interactive/CI mode it uses `sudo -n` and never blocks on a password
prompt.

## macOS

The installer detects Homebrew and maps tools to `brew`. If Homebrew is
missing:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
python3 -m installer
```

## Windows (PowerShell + Winget)

From PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
powershell -ExecutionPolicy Bypass -File installer\windows\install.ps1
```

`install.ps1`:
1. Checks winget (Windows 10 1809+ / App Installer).
2. Installs Python via `winget` if missing.
3. Clones the repo (or downloads the archive).
4. Hands off to `python3 ... installer install`.

Afterwards the global `installer` and `yt-auto` commands are available from a
new terminal.

## Termux

```bash
pkg install python
python -m installer          # uses `pkg`, no root required
```

## Post-install

```bash
installer verify     # status table of all tools
installer doctor     # deeper diagnostics; add --fix to auto-repair
installer status     # where everything lives
installer logs       # last log lines
```

Open a new terminal (or `source ~/.bashrc`) so the new `~/.local/bin` PATH
entry takes effect, then:

```bash
yt-auto setup        # guided first-time configuration
yt-auto oauth        # YouTube OAuth login
yt-auto upload <URL> # process + upload a video
```

## Upgrading

```bash
installer update     # checks GitHub Releases, shows changelog, upgrades
installer repair     # re-run failed/incomplete stages
```

## Uninstalling

```bash
installer uninstall                 # removes source, commands, PATH edits
installer uninstall --remove-config # also delete installer config
installer uninstall --purge         # also delete ~/.yt-mirror data (asks first)
```

`uninstall` never touches `~/.yt-mirror` user data unless you confirm `--purge`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `python3: command not found` | Install Python 3.10+ for your platform first |
| `installer: command not found` | Reopen your terminal or add `~/.local/bin` to PATH |
| Package install fails | Run `installer doctor`; the hint shows the exact command |
| sudo password prompt in CI | Run with `--non-interactive` (uses `sudo -n`) |
| WSL / Docker oddities | Reported by `installer status`; usually cosmetic |
