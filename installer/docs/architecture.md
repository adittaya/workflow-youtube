# Architecture

The installer is a dependency-free Python package (stdlib only) so it can run
on a bare machine. It is split into a stable *core*, swappable *platform
backends*, and thin *service modules* layered on top.

## Module map

```mermaid
graph TD
    subgraph Entry
        CLI[cli.py]
        MAIN[__main__.py]
    end

    subgraph Orchestration
        OPS[operations.py -- install/update/repair pipeline]
        DOC[doctor.py]
        VER[verification.py]
        UNINSTALL[uninstall.py]
        UP[update.py]
    end

    subgraph Services
        DL[downloads.py]
        UI[interactive.py]
        RB[rollback.py]
    end

    subgraph Core
        ENV[core/env.py]
        PKG[core/packages.py]
        CFG[core/config.py]
        ST[core/state.py]
        SP[core/shellprofile.py]
        LOG[core/logging.py]
        UTIL[core/utils.py]
    end

    subgraph Platforms
        BASE[platforms/base.py]
        LIN[platforms/linux.py apt/dnf/pacman/zypper]
        MAC[platforms/macos.py brew]
        TMX[platforms/termux.py pkg]
        WIN[platforms/windows.py winget]
    end

    CLI --> OPS & DOC & VER & UNINSTALL & UP
    OPS --> ENV & PKG & CFG & ST & SP & UI & RB & DL
    OPS --> BASE
    BASE --> LIN & MAC & TMX & WIN
    DOC --> ENV & PKG & CFG & ST
    VER --> PKG & ENV
    UP --> DL
    UI --> UTIL
    PKG --> ENV
    ENV --> UTIL
    SP --> ENV & UTIL
    CFG --> ENV
    LOG --> ENV
    RB --> UTIL
```

## Data flow during `installer install`

```mermaid
sequenceDiagram
    participant U as User/CI
    participant C as cli.py
    participant O as operations.py
    participant E as core/env.py
    participant P as core/packages.py
    participant M as platforms/*.py
    participant S as core/state.py
    participant R as rollback.py

    U->>C: installer install
    C->>O: run_install(ui, config)
    O->>E: detect OS/distro/arch/shell/pm
    O->>S: begin_stage(...)
    O->>P: check installed packages
    O->>M: install missing (apt/dnf/.../winget)
    O->>O: copy source, pip install
    O->>R: record undo steps
    O->>O: write config, install shims, PATH
    O->>S: mark_installed(version)
    O->>R: clear journal on success
    C-->>U: success summary / exit code
```

On failure in a critical stage, `rollback.rollback()` replays undo steps in
reverse (uninstall packages, delete created files, restore overwritten config),
leaving the machine as close to its previous state as possible.

## Key design decisions

- **Dependency-free bootstrap.** The installer cannot assume pip, yt-dlp or
  even a fully populated PATH, so everything uses the standard library.
- **Logical package abstraction.** Code names tools (`git`, `ffmpeg`), not
  packages. `core/packages.py` + `packages.yaml` resolve to per-manager names,
  so a new distro or manager is a backend + a mapping, not a rewrite.
- **State machine with repair.** `core/state.py` records each stage's status.
  `installer repair` re-runs only failed/incomplete stages.
- **Idempotency everywhere.** Shell-profile edits, downloads, config writes and
  re-installs never duplicate work.
- **Least privilege.** Root/`sudo` only used when a privileged manager needs
  it, never for the whole install; `sudo -n` in non-interactive mode.
- **Config wins.** User config merges over defaults; `installer config` edits
  live JSON (or YAML/TOML by extension).

## Extensibility

- *New tool* → add an entry to `packages.yaml` (see `docs/packages.md`).
- *New package manager* → implement the four primitives
  (`install`, `remove`, `update`, `error_hint`) on `platforms/base.py` and
  register it in `platforms/__init__.py`.
- *New platform* → create a `platforms/<name>.py` backend and teach
  `core/env.py` to detect it.
