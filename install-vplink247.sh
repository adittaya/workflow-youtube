#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  vplink247 — One-Line Installer
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/install-vplink247.sh | bash
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO="adittaya/workflow-vplink"
RAW="https://raw.githubusercontent.com/$REPO/main"
BIN="/usr/local/bin/vplink247"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}${1}${NC}"; }
warn() { echo -e "  ${YELLOW}${1}${NC}"; }
fail() { echo -e "  ${RED}${1}${NC}"; }
info() { echo -e "${CYAN}${1}${NC}"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         vplink247 — One-Line Installer       ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Check prerequisites ────────────────────────────────
MISSING=()
for cmd in python3 git; do
  command -v "$cmd" &>/dev/null || MISSING+=("$cmd")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  fail "Missing: ${MISSING[*]} — install them first"
  exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
[ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 8 ] || { fail "Python 3.8+ required (found $PY_MAJOR.$PY_MINOR)"; exit 1; }
ok "Python $PY_MAJOR.$PY_MINOR"

# ── Install pynacl ─────────────────────────────────────
info "Installing pynacl (for GitHub Secrets encryption)..."
PIP_CMD=""
for c in pip3 pip; do
  command -v "$c" &>/dev/null && PIP_CMD="$c" && break
done
if [ -n "$PIP_CMD" ]; then
  PIP_EXTRA=""
  python3 -c "import sys; import site; sys.exit(0 if hasattr(site, 'ENABLE_USER_SITE') and site.ENABLE_USER_SITE else 1)" 2>/dev/null || PIP_EXTRA="--break-system-packages"
  $PIP_CMD install pynacl --quiet $PIP_EXTRA 2>/dev/null || warn "Could not install pynacl ('vplink247 deploy' will fail on secret encryption)"
  ok "pynacl installed"
else
  warn "pip not found; install pynacl manually: pip install pynacl"
fi

# ── Download vplink247 ─────────────────────────────────
info "Downloading vplink247..."
TMPFILE=$(mktemp)
# GitHub API avoids raw CDN caching issues
FETCH_URL="https://api.github.com/repos/$REPO/contents/vplink247.py"
if ! curl -fsSL -H "Accept: application/vnd.github.v3.raw" "$FETCH_URL" -o "$TMPFILE" 2>/dev/null; then
  # fallback: raw CDN
  curl -fsSL "https://raw.githubusercontent.com/$REPO/main/vplink247.py" -o "$TMPFILE" 2>/dev/null
fi
if [ ! -s "$TMPFILE" ]; then
  rm -f "$TMPFILE"
  fail "Failed to download vplink247.py"
  exit 1
fi
if [ -w "$(dirname "$BIN")" ]; then
  mv "$TMPFILE" "$BIN"
  chmod +x "$BIN"
else
  sudo mv "$TMPFILE" "$BIN" 2>/dev/null
  sudo chmod +x "$BIN" 2>/dev/null
fi
ok "Installed: $BIN"

# ── Download github_sync.py ─────────────────────────────
info "Downloading github_sync.py..."
GITHUB_SYNC_BIN="/usr/local/bin/github_sync.py"
TMPFILE2=$(mktemp)
FETCH_URL2="https://api.github.com/repos/$REPO/contents/github_sync.py"
if ! curl -fsSL -H "Accept: application/vnd.github.v3.raw" "$FETCH_URL2" -o "$TMPFILE2" 2>/dev/null; then
  curl -fsSL "https://raw.githubusercontent.com/$REPO/main/github_sync.py" -o "$TMPFILE2" 2>/dev/null
fi
if [ -s "$TMPFILE2" ]; then
  if [ -w "$(dirname "$GITHUB_SYNC_BIN")" ]; then
    mv "$TMPFILE2" "$GITHUB_SYNC_BIN"
  else
    sudo mv "$TMPFILE2" "$GITHUB_SYNC_BIN" 2>/dev/null
  fi
  ok "Installed: $GITHUB_SYNC_BIN"
else
  rm -f "$TMPFILE2"
  warn "Could not download github_sync.py (sync feature will be unavailable)"
fi

mkdir -p "$HOME/.vplink247"

# ── Install Bun (for React TUI) ────────────────────────
TUI_BIN="/usr/local/bin/vplink-tui"
if ! command -v bun &>/dev/null; then
  info "Installing Bun runtime (for React TUI)..."
  curl -fsSL https://bun.sh/install | bash 2>/dev/null
  # add bun to PATH for this session
  export BUN_INSTALL="$HOME/.bun"
  export PATH="$BUN_INSTALL/bin:$PATH"
fi
if command -v bun &>/dev/null; then
  ok "Bun $(bun --version)"
else
  warn "Bun not available — React TUI will not be installed"
fi

# ── Install React TUI ──────────────────────────────────
if command -v bun &>/dev/null; then
  TUI_DIR="$HOME/.vplink247/tui"
  info "Downloading React TUI..."
  mkdir -p "$TUI_DIR"
  # download essential TUI files
  for f in package.json tsconfig.json src/index.tsx src/cli.tsx src/components/App.tsx src/components/Header.tsx src/components/Sidebar.tsx src/screens/Dashboard.tsx src/screens/Deployments.tsx src/screens/Accounts.tsx src/screens/Analytics.tsx src/screens/Settings.tsx src/screens/Sync.tsx src/utils/storage.ts src/services/github.ts src/services/deploy.ts src/hooks/useAppState.ts; do
    DIR=$(dirname "$f")
    mkdir -p "$TUI_DIR/$DIR"
    FETCH="https://api.github.com/repos/$REPO/contents/tui/$f"
    curl -fsSL -H "Accept: application/vnd.github.v3.raw" "$FETCH" -o "$TUI_DIR/$f" 2>/dev/null || \
      curl -fsSL "$RAW/tui/$f" -o "$TUI_DIR/$f" 2>/dev/null || true
  done
  # install dependencies
  if [ -f "$TUI_DIR/package.json" ]; then
    (cd "$TUI_DIR" && bun install --no-save 2>/dev/null) || warn "bun install failed"
  fi
  # create wrapper script
  cat > "$TUI_BIN" << 'TUIEOF'
#!/bin/bash
exec bun run "$HOME/.vplink247/tui/src/cli.tsx" "$@"
TUIEOF
  chmod +x "$TUI_BIN"
  ok "React TUI installed: $TUI_BIN"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  ✓ vplink247 installed!                                 ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║  Next:                                                  ║${NC}"
echo -e "${BOLD}║    vplink-tui                   # React TUI (new!)   ║${NC}"
echo -e "${BOLD}║    vplink247                    # Python CLI (classic)║${NC}"
echo -e "${BOLD}║    vplink247 deploy create       # deploy relay        ║${NC}"
echo -e "${BOLD}║    vplink247 test <repo>         # test your relay     ║${NC}"
echo -e "${BOLD}║    vplink247 status              # view status         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
