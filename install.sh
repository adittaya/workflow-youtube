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

# --- Detect source — local git clone or one-liner ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
REPO_URL="https://github.com/adittaya/workflow-shorturl-yt.git"

if [ -f "$SCRIPT_DIR/mirror.py" ]; then
    COPY_SRC="$SCRIPT_DIR"
    GIT_REMOTE=$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo "$REPO_URL")
    echo "  Source: local clone"
    # Keep the local clone current before installing (only when clean — the
    # developer's uncommitted work is the source of truth and is preserved).
    if git -C "$SCRIPT_DIR" status --porcelain >/dev/null 2>&1 \
        && [ -z "$(git -C "$SCRIPT_DIR" status --porcelain 2>/dev/null)" ]; then
        git -C "$SCRIPT_DIR" pull --ff-only 2>/dev/null && echo "  Local clone updated to latest." || true
    fi
else
    GIT_REMOTE="$REPO_URL"
    COPY_SRC="$INSTALL_DIR/.repo"
    echo "  Source: one-liner (cloning from $REPO_URL)"
    echo "  Cloning repo..."
    rm -rf "$COPY_SRC"
    git clone --depth 1 "$GIT_REMOTE" "$COPY_SRC"
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
pip3 install --break-system-packages -q -r "$COPY_SRC/requirements.txt" 2>/dev/null \
  || pip3 install -q -r "$COPY_SRC/requirements.txt" 2>/dev/null \
  || { echo "  Trying with --user..."; pip3 install --user -q -r "$SCRIPT_DIR/requirements.txt"; }

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
# Copy ALL source so new modules (e.g. verify_state.py) are never missing from
# an existing installation.
cp "$COPY_SRC"/*.py "$SRC_DIR/" 2>/dev/null || true
cp "$COPY_SRC"/*.txt "$SRC_DIR/" 2>/dev/null || true
cp "$COPY_SRC"/*.json "$SRC_DIR/" 2>/dev/null || true
cp "$COPY_SRC"/*.sql "$SRC_DIR/" 2>/dev/null || true
cp "$COPY_SRC/install.sh" "$SRC_DIR/" 2>/dev/null || true
cp "$COPY_SRC/launcher.sh" "$SRC_DIR/" 2>/dev/null || true

# Copy workflows
if [ -d "$COPY_SRC/.github" ]; then
    cp -r "$COPY_SRC/.github" "$SRC_DIR/"
fi

# --- Save metadata ---
META_FILE="$INSTALL_DIR/.install_meta.json"
COMMIT=$(git -C "$COPY_SRC" rev-parse --short HEAD 2>/dev/null || echo "")
REQ_SHA=$(sha256sum "$COPY_SRC/requirements.txt" 2>/dev/null | cut -d' ' -f1)
echo "{\"remote\": \"$GIT_REMOTE\", \"installed_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"commit\": \"$COMMIT\", \"requirements_sha\": \"$REQ_SHA\"}" > "$META_FILE"

# --- Launcher with auto-update ---
echo "[7/7] Installing launcher with auto-update..."
mkdir -p "$BIN_DIR"
if [ -f "$COPY_SRC/launcher.sh" ]; then
    cp "$COPY_SRC/launcher.sh" "$BIN"
    chmod +x "$BIN"
else
    cat > "$BIN" << 'FALLBACK'
#!/usr/bin/env bash
exec python3 "$HOME/.yt-mirror/src/tui.py" "$@"
FALLBACK
    chmod +x "$BIN"
fi

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
echo "  Auto-update: enabled (pulls latest on every VPLINKYT launch)"
echo ""
echo "Run:"
echo "  VPLINKYT              # Open management TUI (auto-updates)"
echo "  VPLINKYT --no-update  # Skip auto-update"
echo "  python3 $SRC_DIR/mirror.py      # Run mirror directly"
echo "  python3 $SRC_DIR/daily_mirror.py # Run daily upload pipeline"
echo "  python3 $SRC_DIR/tui.py          # Open TUI directly"
