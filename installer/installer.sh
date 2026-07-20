#!/usr/bin/env bash
set -euo pipefail

# VPLink 3.0 — Bootstrap CLI
# Usage: curl -fsSL https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/installer/installer.sh | bash
# Or:    bash installer/installer.sh [command]

APP_NAME="vplink3"
PYTHON_MIN="3.10"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Colors ──
BOLD='\033[1m'
RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
NC='\033[0m'

info()  { echo -e "  ${CYAN}•${NC} $1"; }
ok()    { echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $1"; }
error() { echo -e "  ${RED}✗${NC} $1"; }

# ── Help ──
usage() {
    echo "VPLink 3.0 — Cross-Platform Bootstrap Installer"
    echo ""
    echo "Usage: installer.sh <command>"
    echo ""
    echo "Commands:"
    echo "  install    Install all dependencies"
    echo "  update     Self-update"
    echo "  verify     Verify installation"
    echo "  doctor     System diagnostics"
    echo "  config     Manage configuration"
    echo "  status     Show installation status"
    echo "  logs       Show install logs"
    echo "  uninstall  Remove VPLink"
    echo "  help       Show this help"
}

# ── Find Python ──
find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
            if [ "$(echo "$version" | cut -d. -f1)" -ge 3 ] && [ "$(echo "$version" | cut -d. -f2)" -ge 10 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# ── Ensure pip ──
ensure_pip() {
    local python="$1"
    if ! "$python" -m pip --version &>/dev/null; then
        info "Installing pip..."
        "$python" -m ensurepip --upgrade 2>/dev/null || curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$python"
    fi
}

# ── Install deps ──
install_deps() {
    local python="$1"
    info "Installing Python dependencies..."
    if [ -f "$PROJECT_DIR/requirements.txt" ]; then
        "$python" -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet 2>/dev/null || \
        "$python" -m pip install -r "$PROJECT_DIR/requirements.txt" 2>&1 | tail -3
    fi
    "$python" -m pip install --quiet selenium webdriver-manager requests urllib3 2>/dev/null || true
    ok "Dependencies installed"
}

# ── Main ──
main() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║         VPLink 3.0 — Bootstrap CLI          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""

    PYTHON=$(find_python) || true
    if [ -z "$PYTHON" ]; then
        error "Python $PYTHON_MIN+ is required but not found."
        error "Install it: apt install python3 python3-pip (Linux) or brew install python@3 (macOS)"
        exit 1
    fi
    ok "Python $("$PYTHON" --version 2>&1)"

    ensure_pip "$PYTHON"
    install_deps "$PYTHON"

    echo ""
    info "Launching VPLink installer..."
    echo ""
    exec "$PYTHON" -m installer "$@"
}

# ── Dispatch ──
if [ $# -eq 0 ]; then
    set -- install
fi

case "${1:-help}" in
    install|update|verify|doctor|config|status|logs|uninstall)
        COMMAND="$1"
        shift
        main "$COMMAND" "$@"
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        error "Unknown command: $1"
        usage
        exit 1
        ;;
esac
