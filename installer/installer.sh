#!/usr/bin/env bash
set -eo pipefail

# VPLink 3.0 — Bootstrap CLI
# One-line: bash -c "$(curl -fsSL https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/installer/installer.sh)"

APP_NAME="vplink3"
PYTHON_MIN="3.10"
REPO="https://github.com/adittaya/VPLINK-3.0"
INSTALL_DIR="${HOME}/vplink3.0"

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

# ── Find Python ──
find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
            major="${version%%.*}"
            minor="${version#*.}"
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
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

# ── Help ──
usage() {
    echo "VPLink 3.0 — Cross-Platform Bootstrap Installer"
    echo ""
    echo "Usage: bash -c \"\$(curl -fsSL $REPO/main/installer/installer.sh)\""
    echo ""
    echo "Commands:"
    echo "  install    Install all dependencies (default)"
    echo "  update     Self-update"
    echo "  verify     Verify installation"
    echo "  doctor     System diagnostics"
    echo "  config     Manage configuration"
    echo "  status     Show installation status"
    echo "  uninstall  Remove VPLink"
    echo "  help       Show this help"
}

# ── Clone or update repo ──
ensure_project() {
    # Check if we're already in the project (e.g., local clone)
    if [ -d "$(pwd)/installer" ]; then
        PROJECT_DIR="$(pwd)"
        return 0
    fi

    if [ -d "$INSTALL_DIR" ]; then
        if [ -d "$INSTALL_DIR/installer" ]; then
            info "Updating VPLink..."
            git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || true
            PROJECT_DIR="$INSTALL_DIR"
            cd "$PROJECT_DIR"
            return 0
        fi
        # Old install without new installer — re-clone
        warn "Existing install missing installer module — re-cloning..."
        rm -rf "$INSTALL_DIR"
    fi

    info "Cloning VPLink to $INSTALL_DIR..."
    git clone --depth=1 "$REPO" "$INSTALL_DIR"

    if [ ! -d "$INSTALL_DIR/installer" ]; then
        error "Clone failed — installer/ directory not found"
        exit 1
    fi

    PROJECT_DIR="$INSTALL_DIR"
    cd "$PROJECT_DIR"
}

# ── Main ──
main() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║         VPLink 3.0 — Bootstrap CLI          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""

    # Find Python
    PYTHON=$(find_python) || true
    if [ -z "$PYTHON" ]; then
        error "Python $PYTHON_MIN+ not found."
        error "Install it:"
        error "  Ubuntu/Debian: sudo apt install python3 python3-pip"
        error "  macOS:         brew install python@3.12"
        error "  Termux:        pkg install python"
        exit 1
    fi
    ok "Python $("$PYTHON" --version 2>&1)"

    # Ensure pip
    ensure_pip "$PYTHON"

    # Clone/get project
    ensure_project

    # Install Python deps (required for the installer module)
    info "Installing Python dependencies..."
    if [ -f "$PROJECT_DIR/requirements.txt" ]; then
        "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet 2>/dev/null || \
        "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt" 2>&1 | tail -3
    fi
    "$PYTHON" -m pip install --quiet selenium webdriver-manager requests 2>/dev/null || true
    ok "Dependencies installed"

    # Symlink global command
    if [ ! -f /usr/local/bin/vplink3.0 ] 2>/dev/null; then
        if command -v sudo &>/dev/null; then
            sudo ln -sf "$PROJECT_DIR/vplink3.0.sh" /usr/local/bin/vplink3.0 2>/dev/null || true
        fi
    fi

    echo ""
    info "Launching VPLink installer..."
    echo ""

    # Run the Python installer from the project directory
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
