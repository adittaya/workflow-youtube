# Configuration guide

The installer stores its configuration in the platform-standard location:

| Platform | Path |
| --- | --- |
| Linux / Termux | `~/.config/installer/config.json` |
| macOS | `~/Library/Application Support/installer/config.json` |
| Windows | `%APPDATA%\installer\config.json` |

JSON is the default. The file **format follows the extension** — name it
`config.yaml` or `config.toml` to use those formats. A commented example lives
at `installer/config.example.json`.

## Inspect / edit

```bash
installer config show                      # print the merged configuration
installer config set shell_profile no      # change a scalar
installer config set mirror_home ~/videos  # paths are expanded
installer config env YT_COOKIES /secret    # add an env var (see below)
```

Or edit the file directly — user values always win over defaults.

## Keys

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `install_dir` | path | `~/.local/share/yt-auto/src` | where the project source is copied |
| `data_dir` | path | `~/.local/share/yt-auto` | data directory |
| `mirror_home` | path | `~/.yt-mirror` | yt-auto runtime data (videos, state) |
| `shell_profile` | `ask`/`yes`/`no` | `ask` | whether to edit PATH into your shell profile |
| `upgrade` | bool | `false` | also upgrade outdated packages on install |
| `packages` | list | git, python, ffmpeg, yt-dlp | logical packages to install |
| `optional_packages` | list | nodejs, docker, chromium, vscode | reported, never required |
| `pip_packages` | list | yt-dlp, google-api-* | pip tools checked at verify |
| `env` | map | `{}` | extra env vars exported to shell profiles |
| `source_url` | str | — | repo to clone when no local checkout is found |

## Environment variables

`env` entries are written to your shell profile on install (e.g.
`YT_COOKIES=/path/to/cookies.txt`), idempotently — never duplicated:

```bash
installer config env YT_MIRROR_HOME ~/.yt-mirror
installer config env YT_COOKIES /home/me/cookies.txt
```

```json
{
  "env": {
    "YT_MIRROR_HOME": "~/.yt-mirror",
    "YT_COOKIES": "/home/me/cookies.txt"
  }
}
```

Profile updates apply to the *detected* shell (`.bashrc`, `.zshrc`,
`config.fish`, PowerShell `$PROFILE`). Existing `export KEY=…` lines are left
alone; the installer never duplicates or overwrites your own lines.

## YAML example

```yaml
install_dir: ~/.local/share/yt-auto/src
shell_profile: yes
upgrade: false
packages:
  - git
  - python
  - ffmpeg
  - yt-dlp
env:
  YT_MIRROR_HOME: ~/.yt-mirror
```

## TOML example

```toml
install_dir = "~/.local/share/yt-auto/src"
shell_profile = "ask"
upgrade = false

[env]
YT_MIRROR_HOME = "~/.yt-mirror"
```

## State and logs

| File | Purpose |
| --- | --- |
| `config.json` | this configuration |
| `state.json` | per-stage install status (used by `repair`) |
| `rollback.json` | undo journal for failed installs |
| `logs/installer.log` | timestamped, level-prefixed log of every action |
