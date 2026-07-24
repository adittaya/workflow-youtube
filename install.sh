#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  VPLink TUI — One-Line Installer
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/install.sh | bash
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO="adittaya/workflow-vplink"
RAW="https://raw.githubusercontent.com/$REPO/main"
TUI_DIR="$HOME/.vplink247/tui"
TUI_BIN="/usr/local/bin/vplink-tui"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}${1}${NC}"; }
warn() { echo -e "  ${YELLOW}${1}${NC}"; }
fail() { echo -e "  ${RED}${1}${NC}"; exit 1; }
info() { echo -e "${CYAN}${1}${NC}"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         VPLink TUI — One-Line Installer      ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Check git ──────────────────────────────────────────
command -v git &>/dev/null || fail "git required — install it first"

# ── Install Bun ────────────────────────────────────────
if ! command -v bun &>/dev/null; then
  info "Installing Bun runtime..."
  curl -fsSL https://bun.sh/install | bash 2>/dev/null
  export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
  export PATH="$BUN_INSTALL/bin:$PATH"
fi
if ! command -v bun &>/dev/null; then
  fail "Bun installation failed"
fi
ok "Bun $(bun --version)"

# ── Download TUI ───────────────────────────────────────
info "Downloading TUI..."
mkdir -p "$TUI_DIR"

FILES="package.json tsconfig.json"
DIRS="src/components src/screens src/utils src/services src/hooks"

for d in $DIRS; do
  mkdir -p "$TUI_DIR/$d"
done

# download files from GitHub
fetch() {
  local path="$1"
  local dir=$(dirname "$path")
  mkdir -p "$TUI_DIR/$dir"
  curl -fsSL -H "Accept: application/vnd.github.v3.raw" \
    "https://api.github.com/repos/$REPO/contents/tui/$path" \
    -o "$TUI_DIR/$path" 2>/dev/null || \
  curl -fsSL "$RAW/tui/$path" -o "$TUI_DIR/$path" 2>/dev/null || \
    warn "Could not download $path"
}

for f in $FILES; do
  fetch "$f"
done

for f in src/index.tsx src/cli.tsx \
         src/components/App.tsx src/components/Header.tsx src/components/Sidebar.tsx \
         src/screens/Dashboard.tsx src/screens/Deployments.tsx src/screens/Accounts.tsx \
         src/screens/Analytics.tsx src/screens/Settings.tsx src/screens/Sync.tsx \
         src/utils/storage.ts src/services/github.ts src/services/deploy.ts \
         src/hooks/useAppState.ts; do
  fetch "$f"
done

ok "TUI files downloaded"

# ── Install dependencies ───────────────────────────────
if [ -f "$TUI_DIR/package.json" ]; then
  info "Installing dependencies..."
  (cd "$TUI_DIR" && bun install 2>/dev/null) || warn "bun install failed"
  ok "Dependencies installed"
fi

# ── Create wrapper ─────────────────────────────────────
TMPWRAPPER=$(mktemp)
cat > "$TMPWRAPPER" << 'EOF'
#!/bin/bash
exec bun run "$HOME/.vplink247/tui/src/cli.tsx" "$@"
EOF
chmod +x "$TMPWRAPPER"
if [ -w "$(dirname "$TUI_BIN")" ]; then
  mv "$TMPWRAPPER" "$TUI_BIN"
else
  sudo mv "$TMPWRAPPER" "$TUI_BIN"
fi
ok "Installed: $TUI_BIN"

mkdir -p "$HOME/.vplink247"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  ✓ VPLink TUI installed!                                ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║  Next:                                                  ║${NC}"
echo -e "${BOLD}║    vplink-tui                   # launch React TUI      ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
