#!/usr/bin/env bash
set -e

INSTALL_DIR="${YT_MIRROR_HOME:-$HOME/.yt-mirror}"
BIN_DIR="${HOME}/.local/bin"
BIN="${BIN_DIR}/VPLINKYT"
SRC_DIR="${INSTALL_DIR}/src"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║        Y O U T U B E   M I R R O R   I N S T A L L     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --- Detect source dir (where install.sh lives) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$SCRIPT_DIR/mirror.py" ]; then
    echo "ERROR: mirror.py not found next to install.sh"
    echo "Run from the project directory: bash install.sh"
    exit 1
fi

# --- Python ---
echo "[1/6] Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $PY_VER"

# --- Pip deps ---
echo "[2/6] Installing Python dependencies..."
pip3 install --break-system-packages -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null \
  || pip3 install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null \
  || { echo "  Trying with --user..."; pip3 install --user -q -r "$SCRIPT_DIR/requirements.txt"; }

# --- yt-dlp ---
echo "[3/6] Checking yt-dlp..."
if command -v yt-dlp &>/dev/null; then
    echo "  yt-dlp: $(yt-dlp --version 2>/dev/null || echo 'installed')"
else
    echo "  Installing yt-dlp..."
    pip3 install --break-system-packages -q yt-dlp 2>/dev/null \
      || pip3 install -q yt-dlp 2>/dev/null \
      || pip3 install --user -q yt-dlp
fi

# --- Data dir ---
echo "[4/6] Setting up data directory..."
mkdir -p "$INSTALL_DIR"
for f in config.json channels.json state.json accounts.json github_accounts.json settings.json deployments.json status_cache.json shortlink_keys.json; do
    [ -f "$INSTALL_DIR/$f" ] || echo "{}" > "$INSTALL_DIR/$f"
done

# --- Copy source files ---
echo "[5/6] Copying source files..."
mkdir -p "$SRC_DIR"
cp "$SCRIPT_DIR"/config.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/mirror.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/monitor.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/youtube_api.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/shortener.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/download_helpers.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/github_api.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/get_refresh_token.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/tui.py "$SRC_DIR/"
cp "$SCRIPT_DIR"/requirements.txt "$SRC_DIR/"
cp "$SCRIPT_DIR"/client_secrets.json "$SRC_DIR/" 2>/dev/null || true

# Copy workflows
if [ -d "$SCRIPT_DIR/.github" ]; then
    cp -r "$SCRIPT_DIR/.github" "$SRC_DIR/"
fi

# --- Launcher ---
echo "[6/6] Installing launcher..."
mkdir -p "$BIN_DIR"
cat > "$BIN" << WRAPPER
#!/usr/bin/env bash
cd "$SRC_DIR"
exec python3 "$SRC_DIR/tui.py" "\$@"
WRAPPER
chmod +x "$BIN"

if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    echo "  Added ~/.local/bin to PATH (run 'source ~/.bashrc' or open new terminal)"
fi

echo ""
echo "✓ Installed!"
echo ""
echo "  Source:  $SRC_DIR"
echo "  Config:  $INSTALL_DIR"
echo "  Binary:  $BIN"
echo ""
echo "Run:"
echo "  yt-mirror          # Open management TUI"
echo "  python3 $SRC_DIR/mirror.py   # Run mirror directly"
echo "  python3 $SRC_DIR/tui.py      # Open TUI directly"
