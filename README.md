# VPLink 3.0

Automated vplink.in funnel — runs views in rotation, captures final destination URL.

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/install.sh | bash
```

Works on: **Ubuntu**, **Debian**, **Fedora**, **RHEL**, **Arch**, **openSUSE**, **Alpine**, **macOS**, and **Termux** (Android).

After install, just run:

```bash
vplink3.0
```

## What it does

1. Installs the required Playwright/Chromium dependencies
2. Installs Node.js 20+ if missing
3. Clones the repo to `~/vplink3.0`
4. Installs npm packages & Playwright Chromium browser
5. Symlinks the `vplink3.0` command to `/usr/local/bin` (or `$PREFIX/bin` on Termux)

## Usage

```
vplink3.0
```

Prompts for:
- **vplink key** — the key from vplink.in URL
- **views** — how many times to run
- optional profile settings

Each invocation stores results in `results/<timestamp-pid>/`, preserving results from earlier runs.

## Manual setup

```bash
git clone https://github.com/adittaya/VPLINK-3.0 ~/vplink3.0
cd ~/vplink3.0
npm install
npx playwright install chromium
sudo ln -sf "$(pwd)/vplink3.0.sh" /usr/local/bin/vplink3.0
sudo chmod +x /usr/local/bin/vplink3.0
vplink3.0
```
