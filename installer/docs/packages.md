# Adding packages

Packages are data, not code. Everything lives in `installer/packages.yaml`.

## Structure

```yaml
packages:
  <logical-name>:
    description: Human-readable purpose
    verify: <binary-probed-for-presence/version>   # optional
    min_version: "1.2"                              # optional gate
    optional: true                                  # default false
    systems:
      apt: [pkg-names]
      dnf: [pkg-names]
      pacman: [pkg-names]
      zypper: [pkg-names]
      brew: [pkg-names]
      pkg: [pkg-names]          # Termux
      winget: [Winget.Ids]      # Windows

pip_packages:
  <tool-name>:
    description: ...
    verify: <binary>            # optional
```

## Example: add `jq`

```yaml
  jq:
    description: JSON command-line processor
    verify: jq
    min_version: "1.6"
    systems:
      apt: [jq]
      dnf: [jq]
      pacman: [jq]
      zypper: [jq]
      brew: [jq]
      pkg: [jq]
      winget: [jq.is]
```

Then add `jq` to the `packages` list in your config and run `installer install`.
It will now appear in `installer verify` and `installer doctor` automatically.

## Rules

1. **Every supported manager needs a mapping** — if a manager has no mapping
   for a tool, the installer logs it and skips it (it never fails a whole
   install because of one tool).
2. **`verify`** should be the binary on PATH (`git`, `ffmpeg`, `node`).
   Version-gated tools with no clean binary (e.g. pip modules) can omit it.
3. **`min_version`** is advisory: an older installed tool is reported by
   `verify`/`doctor` as failing its requirement, but not force-upgraded.
4. **`optional: true`** tools never block installs or fail `verify` — they are
   shown as `optional`.
5. Keep the YAML in the small subset the dependency-free parser understands:
   nested mappings and inline lists (`apt: [git]`), one value per line.

## Finding Winget IDs

```powershell
winget search <tool>        # e.g. winget search jq
```

## Writing a custom platform backend

Implement the four primitives from `installer/platforms/base.py`:

```python
from installer.platforms.base import PlatformInstaller

class XbpsInstaller(PlatformInstaller):
    name = "xbps"
    def install(self, packages, dry_run=False): ...
    def remove(self, packages, dry_run=False): ...
    def update(self, dry_run=False): ...
    def error_hint(self, packages): ...
```

Register it in `platforms/__init__.py` and add a detection branch in
`core/env.py#package_manager()`. Done — `install_package("git")` now works on
that platform too.
