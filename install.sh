#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  VPLink — One-Line Installer
#  Installs: vplink-gui (Web GUI) + vplink-tui (Terminal UI)
#
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/install.sh | bash
#
#  Options (pipe after bash):
#    bash -s -- --gui-only     # install Web GUI only
#    bash -s -- --tui-only     # install TUI only
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO="adittaya/workflow-vplink"
RAW="https://raw.githubusercontent.com/$REPO/main"
VPLINK_HOME="$HOME/.vplink247"
WEB_DIR="$VPLINK_HOME/web"
TUI_DIR="$VPLINK_HOME/tui"
GUI_BIN="/usr/local/bin/vplink-gui"
TUI_BIN="/usr/local/bin/vplink-tui"

INSTALL_GUI=true
INSTALL_TUI=true

for arg in "$@"; do
  case "$arg" in
    --gui-only) INSTALL_TUI=false ;;
    --tui-only) INSTALL_GUI=false ;;
  esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} ${1}"; }
warn() { echo -e "  ${YELLOW}⚠${NC} ${1}"; }
fail() { echo -e "  ${RED}✗${NC} ${1}"; exit 1; }
info() { echo -e "${CYAN}  ${1}${NC}"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         ⚡ VPLink — One-Line Installer           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Check requirements ────────────────────────────────
command -v python3 &>/dev/null || fail "python3 required"
ok "Python $(python3 --version 2>&1 | awk '{print $2}')"

# ── Create directories ────────────────────────────────
mkdir -p "$VPLINK_HOME" "$WEB_DIR/server" "$WEB_DIR/client/dist" "$TUI_DIR"

# ═══════════════════════════════════════════════════════════════
#  PART 1: Web GUI (vplink-gui)
# ═══════════════════════════════════════════════════════════════
if [ "$INSTALL_GUI" = true ]; then
  echo -e "\n${BOLD}── Web GUI ──${NC}"

  # Download API server
  info "Downloading API server..."
  fetch_github() {
    local path="$1"
    local dest="$2"
    local dir=$(dirname "$dest")
    mkdir -p "$dir"
    curl -fsSL -H "Accept: application/vnd.github.v3.raw" \
      "https://api.github.com/repos/$REPO/contents/$path" \
      -o "$dest" 2>/dev/null || \
    curl -fsSL "$RAW/$path" -o "$dest" 2>/dev/null || \
      warn "Could not download $path"
  }

  fetch_github "web/server/app.py" "$WEB_DIR/server/app.py"
  fetch_github "web/start.sh" "$WEB_DIR/start.sh"
  chmod +x "$WEB_DIR/start.sh" 2>/dev/null || true

  # Download pre-built frontend
  info "Downloading frontend..."
  fetch_github "web/client/dist/index.html" "$WEB_DIR/client/dist/index.html"

  # Download CSS and JS from latest release assets or build from source
  # Since we can't easily download dist assets from GitHub API (they're gitignored),
  # we download the source and build if Node.js is available
  if command -v npm &>/dev/null || command -v npx &>/dev/null; then
    info "Building frontend from source..."
    TMPDIR=$(mktemp -d)
    fetch_github "web/client/package.json" "$TMPDIR/package.json"
    fetch_github "web/client/vite.config.ts" "$TMPDIR/vite.config.ts"
    fetch_github "web/client/tailwind.config.js" "$TMPDIR/tailwind.config.js"
    fetch_github "web/client/postcss.config.js" "$TMPDIR/postcss.config.js"
    fetch_github "web/client/tsconfig.json" "$TMPDIR/tsconfig.json"
    fetch_github "web/client/index.html" "$TMPDIR/index.html"

    for f in src/main.tsx src/App.tsx src/services/api.ts \
             src/hooks/useAppState.ts src/hooks/useToast.tsx \
             src/styles/globals.css \
             src/pages/Dashboard.tsx src/pages/Deployments.tsx \
             src/pages/Accounts.tsx src/pages/Settings.tsx \
             src/pages/Analytics.tsx src/pages/Sync.tsx; do
      fetch_github "web/client/$f" "$TMPDIR/$f"
    done

    if (cd "$TMPDIR" && npm install --silent 2>/dev/null && npx vite build --silent 2>/dev/null); then
      cp -r "$TMPDIR/dist/"* "$WEB_DIR/client/dist/" 2>/dev/null || true
      ok "Frontend built"
    else
      warn "Frontend build failed — GUI will show placeholder"
      echo "<html><body style='background:#0f0f23;color:white;display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui'><div style='text-align:center'><h1>⚡ VPLink GUI</h1><p>Frontend build failed. Run manually:</p><code>cd ~/.vplink247/web/client && npm install && npx vite build</code></div></body></html>" > "$WEB_DIR/client/dist/index.html"
    fi
    rm -rf "$TMPDIR"
  else
    warn "npm not found — frontend placeholder only"
    echo "<html><body style='background:#0f0f23;color:white;display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui'><div style='text-align:center'><h1>⚡ VPLink GUI</h1><p>Install Node.js to build the frontend:</p><code>curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - && sudo apt install -y nodejs</code></div></body></html>" > "$WEB_DIR/client/dist/index.html"
  fi

  # Download launcher script
  fetch_github "web/vplink-gui" "$WEB_DIR/vplink-gui"
  chmod +x "$WEB_DIR/vplink-gui" 2>/dev/null || true

  # Create global command
  TMPWRAPPER=$(mktemp)
  printf '#!/bin/bash\nexec "%s" "$@"\n' "$WEB_DIR/vplink-gui" > "$TMPWRAPPER"
  chmod +x "$TMPWRAPPER"
  if [ -w "$(dirname "$GUI_BIN")" ]; then
    mv "$TMPWRAPPER" "$GUI_BIN"
  else
    sudo mv "$TMPWRAPPER" "$GUI_BIN"
  fi
  ok "Installed: $GUI_BIN"
fi

# ═══════════════════════════════════════════════════════════════
#  PART 2: Terminal UI (vplink-tui)
# ═══════════════════════════════════════════════════════════════
if [ "$INSTALL_TUI" = true ]; then
  echo -e "\n${BOLD}── Terminal UI ──${NC}"

  # Install Bun if needed
  if ! command -v bun &>/dev/null; then
    info "Installing Bun runtime..."
    curl -fsSL https://bun.sh/install | bash 2>/dev/null
    export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
    export PATH="$BUN_INSTALL/bin:$PATH"
  fi
  if command -v bun &>/dev/null; then
    ok "Bun $(bun --version)"
  else
    warn "Bun not available — skipping TUI"
    INSTALL_TUI=false
  fi
fi

if [ "$INSTALL_TUI" = true ]; then
  info "Downloading TUI..."
  mkdir -p "$TUI_DIR"
  for d in src/components src/screens src/utils src/services src/hooks; do
    mkdir -p "$TUI_DIR/$d"
  done

  fetch_tui() {
    local path="$1"
    local dir=$(dirname "$path")
    mkdir -p "$TUI_DIR/$dir"
    curl -fsSL -H "Accept: application/vnd.github.v3.raw" \
      "https://api.github.com/repos/$REPO/contents/tui/$path" \
      -o "$TUI_DIR/$path" 2>/dev/null || \
    curl -fsSL "$RAW/tui/$path" -o "$TUI_DIR/$path" 2>/dev/null || \
      warn "Could not download $path"
  }

  for f in package.json tsconfig.json \
           src/index.tsx src/cli.tsx \
           src/components/App.tsx src/components/Header.tsx src/components/Sidebar.tsx \
           src/screens/Dashboard.tsx src/screens/Deployments.tsx src/screens/Accounts.tsx \
           src/screens/Analytics.tsx src/screens/Settings.tsx src/screens/Sync.tsx \
           src/utils/storage.ts src/services/github.ts src/services/deploy.ts \
           src/hooks/useAppState.ts; do
    fetch_tui "$f"
  done
  ok "TUI files downloaded"

  if [ -f "$TUI_DIR/package.json" ]; then
    info "Installing TUI dependencies..."
    (cd "$TUI_DIR" && bun install 2>/dev/null) || warn "bun install failed"
    ok "TUI dependencies installed"
  fi

  BUN_PATH="${BUN_INSTALL:-$HOME/.bun}/bin/bun"
  if [ ! -x "$BUN_PATH" ]; then
    BUN_PATH=$(which bun 2>/dev/null || echo "")
  fi
  if [ -x "$BUN_PATH" ]; then
    TMPWRAPPER=$(mktemp)
    printf '#!/bin/bash\nexport PATH="%s:$PATH"\nexec "%s" run "$HOME/.vplink247/tui/src/cli.tsx" "$@"\n' "$BUN_PATH" "$BUN_PATH" > "$TMPWRAPPER"
    chmod +x "$TMPWRAPPER"
    if [ -w "$(dirname "$TUI_BIN")" ]; then
      mv "$TMPWRAPPER" "$TUI_BIN"
    else
      sudo mv "$TMPWRAPPER" "$TUI_BIN"
    fi
    ok "Installed: $TUI_BIN"
  fi
fi

# ═══════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  ⚡ VPLink installed!                                    ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
if [ "$INSTALL_GUI" = true ]; then
echo -e "${BOLD}║  ${GREEN}vplink-gui${NC}${BOLD}              Open Web Control Center       ║${NC}"
fi
if [ "$INSTALL_TUI" = true ] && [ -x "$TUI_BIN" ]; then
echo -e "${BOLD}║  ${CYAN}vplink-tui${NC}${BOLD}              Launch Terminal UI            ║${NC}"
fi
echo -e "${BOLD}║                                                          ║${NC}"
echo -e "${BOLD}║  ${DIM}vplink-gui --help            Show all options${NC}${BOLD}         ║${NC}"
echo -e "${BOLD}║  ${DIM}vplink-gui --port 8080       Use custom port${NC}${BOLD}          ║${NC}"
echo -e "${BOLD}║  ${DIM}vplink-gui --no-browser      Don't auto-open browser${NC}${BOLD} ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
