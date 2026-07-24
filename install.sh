#!/usr/bin/env bash
set -e

INSTALL_DIR="${VPLINK_HOME:-$HOME/.vplink247}"
REPO="adittaya/workflow-vplink"
BIN="/usr/local/bin/vplink"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║           V P L I N K   I N S T A L L E R              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --- Python ---
echo "[1/4] Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PYVER"

# --- Pip deps ---
echo "[2/4] Installing Python dependencies..."
pip3 install --break-system-packages -q selenium webdriver-manager requests urllib3 cryptography pynacl 2>/dev/null \
  || pip3 install -q selenium webdriver-manager requests urllib3 cryptography pynacl

# --- Chromium (informational) ---
echo "[3/4] Checking Chromium..."
if command -v chromium &>/dev/null; then
    echo "  Chromium: $(chromium --version 2>/dev/null || echo 'installed')"
elif command -v google-chrome &>/dev/null; then
    echo "  Chrome: $(google-chrome --version 2>/dev/null || echo 'installed')"
else
    echo "  WARNING: No browser found. Automation needs Chromium or Chrome."
    echo "  Install: sudo apt install -y chromium-browser"
fi

# --- TUI launcher ---
echo "[4/4] Installing vplink launcher..."

# Remove old Node.js install if present
if [ -L "$HOME/.local/bin/vplink" ]; then
    rm -f "$HOME/.local/bin/vplink"
fi
if [ -d "$HOME/vplink" ] && [ -f "$HOME/vplink/cli.sh" ]; then
    echo "  Removing old Node.js installation at ~/vplink/..."
    rm -rf "$HOME/vplink"
fi

# Download tui.py
curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/tui.py" -o /tmp/vplink_tui.py

# Also download core automation files
for f in automation.py config.py profile_generator.py proxy_rotator.py continuous.yml requirements.txt; do
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/$f" -o "/tmp/vplink_$f" 2>/dev/null || true
done

# Create install dir
mkdir -p "$INSTALL_DIR"

# Move automation files into place
mv /tmp/vplink_automation.py "$INSTALL_DIR/automation.py" 2>/dev/null
mv /tmp/vplink_config.py "$INSTALL_DIR/config.py" 2>/dev/null
mv /tmp/vplink_profile_generator.py "$INSTALL_DIR/profile_generator.py" 2>/dev/null
mv /tmp/vplink_proxy_rotator.py "$INSTALL_DIR/proxy_rotator.py" 2>/dev/null
mv /tmp/vplink_requirements.txt "$INSTALL_DIR/requirements.txt" 2>/dev/null

# Create wrapper script
cat > "$BIN" << 'WRAPPER'
#!/usr/bin/env bash
exec python3 "${VPLINK_HOME:-$HOME/.vplink247}/tui.py" "$@"
WRAPPER
chmod +x "$BIN"

# Also symlink to ~/.local/bin for user-local access
mkdir -p "$HOME/.local/bin"
ln -sf "$BIN" "$HOME/.local/bin/vplink"

# Install TUI
mv /tmp/vplink_tui.py "$INSTALL_DIR/tui.py"

# Init data files
for f in accounts.json deployments.json settings.json; do
    [ -f "$INSTALL_DIR/$f" ] || echo "{}" > "$INSTALL_DIR/$f"
done

# Clone template repo (needed for deploy)
if [ ! -d "$INSTALL_DIR/template" ]; then
    echo "  Cloning template repo..."
    git clone --depth 1 "https://github.com/${REPO}.git" "$INSTALL_DIR/template" 2>/dev/null || true
fi

echo ""
echo "✓ Installed to $INSTALL_DIR"
echo "✓ Run with: vplink"
echo ""
echo "Next steps:"
echo "  1. Run 'vplink' to open the TUI"
echo "  2. Go to Accounts → Add your GitHub token"
echo "  3. Go to Settings → Set Supabase credentials"
echo "  4. Go to Deploy → Create a new instance"
