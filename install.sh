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
command -v git &>/dev/null     || fail "git required"
command -v curl &>/dev/null    || fail "curl required"
ok "Python $(python3 --version 2>&1 | awk '{print $2}')"
ok "Git $(git --version 2>&1 | awk '{print $3}')"

# ── Create directories ────────────────────────────────
mkdir -p "$VPLINK_HOME" "$WEB_DIR" "$TUI_DIR"

# ── Clone repo (shallow) ─────────────────────────────
info "Downloading VPLink repo..."
CLONE_DIR=$(mktemp -d)
git clone --depth 1 --quiet "https://github.com/$REPO.git" "$CLONE_DIR" 2>/dev/null || \
  fail "Could not clone repo"
ok "Repository cloned"

# ═══════════════════════════════════════════════════════════════
#  PART 1: Web GUI (vplink-gui)
# ═══════════════════════════════════════════════════════════════
if [ "$INSTALL_GUI" = true ]; then
  echo -e "\n${BOLD}── Web GUI ──${NC}"

  # Copy API server
  info "Installing API server..."
  mkdir -p "$WEB_DIR/server"
  cp "$CLONE_DIR/web/server/app.py" "$WEB_DIR/server/app.py"
  ok "API server installed"

  # Copy launcher script
  cp "$CLONE_DIR/web/vplink-gui" "$WEB_DIR/vplink-gui"
  chmod +x "$WEB_DIR/vplink-gui"
  ok "Launcher script installed"

  # Build frontend
  if command -v npm &>/dev/null; then
    info "Building frontend (this may take a minute)..."
    mkdir -p "$WEB_DIR/client"
    cp -r "$CLONE_DIR/web/client/"* "$WEB_DIR/client/" 2>/dev/null || true
    # Remove node_modules if copied (we'll reinstall)
    rm -rf "$WEB_DIR/client/node_modules" 2>/dev/null || true
    if (cd "$WEB_DIR/client" && npm install --silent 2>/dev/null && npx vite build 2>/dev/null); then
      ok "Frontend built successfully"
    else
      warn "Frontend build failed — using placeholder"
      mkdir -p "$WEB_DIR/client/dist"
      cat > "$WEB_DIR/client/dist/index.html" <<'PLACEHOLDER'
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VPLink GUI</title></head>
<body style="background:#0f0f23;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;margin:0">
<div style="text-align:center;max-width:400px;padding:2rem">
<h1 style="font-size:2rem;margin-bottom:1rem">⚡ VPLink GUI</h1>
<p style="color:#9ca3af;margin-bottom:1.5rem">Frontend build failed. Run manually:</p>
<code style="background:#1e1b4b;padding:0.75rem 1rem;border-radius:0.75rem;display:block;color:#818cf8;font-size:0.875rem">
cd ~/.vplink247/web/client && npm install && npx vite build
</code>
</div></body></html>
PLACEHOLDER
    fi
  else
    warn "npm not found — installing Node.js..."
    if command -v apt-get &>/dev/null; then
      curl -fsSL https://deb.nodesource.com/setup_20.x 2>/dev/null | bash - 2>/dev/null
      apt-get install -y nodejs 2>/dev/null || true
    fi
    if command -v npm &>/dev/null; then
      ok "Node.js $(node --version) installed"
      info "Building frontend..."
      mkdir -p "$WEB_DIR/client"
      cp -r "$CLONE_DIR/web/client/"* "$WEB_DIR/client/" 2>/dev/null || true
      rm -rf "$WEB_DIR/client/node_modules" 2>/dev/null || true
      if (cd "$WEB_DIR/client" && npm install --silent 2>/dev/null && npx vite build 2>/dev/null); then
        ok "Frontend built successfully"
      else
        warn "Frontend build failed"
        mkdir -p "$WEB_DIR/client/dist"
        echo '<html><body style="background:#0f0f23;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui"><div style="text-align:center"><h1>⚡ VPLink GUI</h1><p style="color:#9ca3af">Build failed. Run: cd ~/.vplink247/web/client && npm install && npx vite build</p></div></body></html>' > "$WEB_DIR/client/dist/index.html"
      fi
    else
      warn "Could not install Node.js — placeholder only"
      mkdir -p "$WEB_DIR/client/dist"
      echo '<html><body style="background:#0f0f23;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui"><div style="text-align:center"><h1>⚡ VPLink GUI</h1><p style="color:#9ca3af">Install Node.js: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - && sudo apt install -y nodejs</p></div></body></html>' > "$WEB_DIR/client/dist/index.html"
    fi
  fi

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
  info "Installing TUI..."
  cp -r "$CLONE_DIR/tui/"* "$TUI_DIR/" 2>/dev/null || true
  rm -rf "$TUI_DIR/node_modules" 2>/dev/null || true
  ok "TUI files installed"

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

# ── Cleanup ───────────────────────────────────────────
rm -rf "$CLONE_DIR"

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
