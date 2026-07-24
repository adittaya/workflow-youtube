# vplink247

24/7 VPLink automation — deploy, manage, and monitor endless relay chains on GitHub Actions.

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/install-vplink247.sh | bash
```

Installs the React TUI (`vplink-tui`) and Python CLI (`vplink247`).

## React TUI (recommended)

```bash
vplink-tui
```

Interactive terminal UI built with React + OpenTUI.

## Python CLI (classic)

```bash
vplink247 account add        # Add GitHub account
vplink247 deploy create      # Deploy automation
vplink247 test <repo>        # Test relay
vplink247 status             # Overall status
```

## How it works

Each deployed repo runs a GitHub Actions workflow that:
1. Gets a premium proxy from the Supabase pool
2. Runs the vplink.in funnel (TP → CE → destination)
3. On success, triggers the next run via repository_dispatch (endless relay chain)
4. On failure, invalidates the proxy and still continues the chain

Cron fallback every 15 minutes.
