# VPLink 3.0

Automated vplink.in funnel — runs views, captures destination URLs.

## One-line install

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/installer/installer.sh)"
```

Works on: **Ubuntu**, **Debian**, **Fedora**, **Arch**, **openSUSE**, **macOS**, **Windows**, **Termux**.

After install, verify:

```bash
python3 -m installer status
```

## Quick start

```bash
git clone https://github.com/adittaya/VPLINK-3.0
cd VPLINK-3.0
python3 -m pip install -r requirements.txt
python3 automation.py <your-key>
```

Or with interactive setup:

```bash
bash vplink3.0.sh
```

## What it is

- Python 3 + Selenium + ChromeDriver automation
- Runs through article funnels (TP → CE → LINK1S) to reach vplink.in destination
- Proxy rotation with session-based IP reuse
- Mobile emulation, YouTube referral, human-like behavior

## Installer commands

```bash
python3 -m installer install     # Full one-time setup
python3 -m installer status      # Check installed packages
python3 -m installer verify      # Verify all dependencies
python3 -m installer doctor      # System diagnostics
python3 -m installer config      # Manage credentials
python3 -m installer logs        # Show install logs
python3 -m installer uninstall   # Remove config
```

## Requirements

- Python 3.10+
- Chromium / Chrome 120+
- Linux (Xvfb + x11vnc optional for debug)
- Supabase account (for proxy rotation)
