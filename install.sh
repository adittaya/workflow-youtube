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
echo "[1/7] Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $PY_VER"

# --- ffmpeg ---
echo "[2/7] Checking ffmpeg..."
if command -v ffmpeg &>/dev/null; then
    echo "  ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 || echo 'installed')"
else
    echo "  WARNING: ffmpeg not found. Video processing requires ffmpeg."
    echo "  Install: sudo apt install ffmpeg"
fi

# --- Pip deps ---
echo "[3/7] Installing Python dependencies..."
pip3 install --break-system-packages -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null \
  || pip3 install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null \
  || { echo "  Trying with --user..."; pip3 install --user -q -r "$SCRIPT_DIR/requirements.txt"; }

# --- Processing deps (torch/demucs — optional, ~2GB) ---
echo "[3b/7] Video processing deps (torch, demucs)..."
if [ "${YT_MIRROR_NO_PROCESSING:-0}" = "1" ]; then
    echo "  Skipped (YT_MIRROR_NO_PROCESSING=1)"
else
    pip3 install --break-system-packages -q -r "$SCRIPT_DIR/requirements-processing.txt" 2>/dev/null \
      || pip3 install -q -r "$SCRIPT_DIR/requirements-processing.txt" 2>/dev/null \
      || { echo "  Skipped (install failed — video processing disabled)"; }
fi

# --- yt-dlp ---
echo "[4/7] Checking yt-dlp..."
if command -v yt-dlp &>/dev/null; then
    echo "  yt-dlp: $(yt-dlp --version 2>/dev/null || echo 'installed')"
else
    echo "  Installing yt-dlp..."
    pip3 install --break-system-packages -q yt-dlp 2>/dev/null \
      || pip3 install -q yt-dlp 2>/dev/null \
      || pip3 install --user -q yt-dlp
fi

# --- Data dir ---
echo "[5/7] Setting up data directory..."
mkdir -p "$INSTALL_DIR"
for f in config.json channels.json state.json accounts.json github_accounts.json settings.json deployments.json status_cache.json shortlink_keys.json upload_state.json daily_log.json warmup_state.json bgm_index.json; do
    [ -f "$INSTALL_DIR/$f" ] || echo "{}" > "$INSTALL_DIR/$f"
done
mkdir -p "$INSTALL_DIR/bgm" "$INSTALL_DIR/separated" "$INSTALL_DIR/processed"

# --- Copy source files ---
echo "[6/7] Copying source files..."
mkdir -p "$SRC_DIR"
for py in config.py mirror.py monitor.py youtube_api.py shortener.py download_helpers.py github_api.py get_refresh_token.py tui.py video_processor.py audio_separator.py bgm_manager.py daily_uploader.py daily_mirror.py; do
    cp "$SCRIPT_DIR/$py" "$SRC_DIR/"
done
cp "$SCRIPT_DIR/requirements.txt" "$SRC_DIR/"
cp "$SCRIPT_DIR/client_secrets.json" "$SRC_DIR/" 2>/dev/null || true

# Copy workflows
if [ -d "$SCRIPT_DIR/.github" ]; then
    cp -r "$SCRIPT_DIR/.github" "$SRC_DIR/"
fi

# --- Launcher ---
echo "[7/7] Installing launcher..."
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
echo "  VPLINKYT              # Open management TUI"
echo "  python3 $SRC_DIR/mirror.py      # Run mirror directly"
echo "  python3 $SRC_DIR/daily_mirror.py # Run daily upload pipeline"
echo "  python3 $SRC_DIR/tui.py          # Open TUI directly"
