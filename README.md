# VPLink TUI

24/7 VPLink automation — deploy, manage, and monitor endless relay chains on GitHub Actions.

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/install.sh | bash
```

Installs the React TUI (`vplink-tui`).

## Usage

```bash
vplink-tui
```

Interactive terminal UI built with React + OpenTUI.

## How it works

Each deployed repo runs a GitHub Actions workflow that:
1. Gets a premium proxy from the Supabase pool
2. Runs the vplink.in funnel (TP → CE → destination)
3. On success, triggers the next run via repository_dispatch (endless relay chain)
4. On failure, invalidates the proxy and still continues the chain

Cron fallback every 15 minutes.
