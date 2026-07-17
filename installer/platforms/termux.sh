#!/usr/bin/env bash
# installer/platforms/termux.sh — Termux (Android) specific installation logic
# Handles Termux-specific quirks: no sudo, different paths, package names,
# storage permissions, x11-repo, and PRoot compatibility.
# All functions are idempotent (safe to re-run).

TERMUX_MIN_NODE_MAJOR="${TERMUX_MIN_NODE_MAJOR:-18}"

# ───────────────────────────────────────────────────────────────
#  Environment detection
# ───────────────────────────────────────────────────────────────

termux_is_termux() {
  [ -n "${PREFIX:-}" ] && [ -d /data/data/com.termux ] 2>/dev/null
}

termux_detect_environment() {
  if ! termux_is_termux; then
    return 1
  fi

  export TERMUX_PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
  export TERMUX_VERSION="${TERMUX_VERSION:-unknown}"
  export HOME="${HOME:-/data/data/com.termux/files/home}"

  # Detect architecture
  TERMUX_ARCH=$(uname -m)
  case "$TERMUX_ARCH" in
    aarch64|arm64) TERMUX_ARCH="aarch64" ;;
    armv7l|armhf) TERMUX_ARCH="armv7l" ;;
    x86_64|amd64) TERMUX_ARCH="x86_64" ;;
    i686|i386)     TERMUX_ARCH="i686" ;;
    *)             TERMUX_ARCH="unknown" ;;
  esac

  # Detect Android version (affects package compatibility)
  TERMUX_ANDROID_SDK=""
  if [ -n "${ANDROID_VERSION:-}" ]; then
    TERMUX_ANDROID_SDK="$ANDROID_VERSION"
  elif [ -f /system/build.prop ]; then
    TERMUX_ANDROID_SDK=$(getprop ro.build.version.sdk 2>/dev/null || echo "")
  fi

  return 0
}

# ───────────────────────────────────────────────────────────────
#  Prerequisites
# ───────────────────────────────────────────────────────────────

termux_install_prerequisites() {
  set -euo pipefail

  if ! termux_is_termux; then
    warn "Not running in Termux — skipping"
    return 1
  fi

  termux_detect_environment || true

  info "Updating Termux packages..."
  pkg update -y 2>/dev/null || apt update -y 2>/dev/null || true

  local packages=(
    curl
    wget
    git
    jq
    make
    gcc
    python
    xz-utils
    unzip
    ca-certificates
    openssh
  )

  info "Installing base packages via pkg..."
  for pkg_name in "${packages[@]}"; do
    if pkg list-installed 2>/dev/null | grep -q "^${pkg_name}/"; then
      debug "  $pkg_name already installed"
    else
      info "  Installing $pkg_name..."
      pkg install -y "$pkg_name" 2>/dev/null \
        || apt install -y "$pkg_name" 2>/dev/null \
        || warn "Failed to install $pkg_name"
    fi
  done

  # Install build packages (needed for native npm modules)
  local build_pkgs=(
    binutils
    patchelf
    libffi
    libffi-dev
    openssl
    openssl-tool
  )

  for pkg_name in "${build_pkgs[@]}"; do
    if ! pkg list-installed 2>/dev/null | grep -q "^${pkg_name}/"; then
      pkg install -y "$pkg_name" 2>/dev/null \
        || apt install -y "$pkg_name" 2>/dev/null \
        || true
    fi
  done

  # Ensure LD_PRELOAD workaround for Termux
  _termux_setup_ld_preload

  log "Termux prerequisites installed"
}

# ───────────────────────────────────────────────────────────────
#  Node.js
# ───────────────────────────────────────────────────────────────

termux_install_node() {
  set -euo pipefail
  local min_major="${1:-$TERMUX_MIN_NODE_MAJOR}"

  if ! termux_is_termux; then
    warn "Not running in Termux — skipping"
    return 1
  fi

  # Check existing
  if termux_node_meets_requirement "$min_major"; then
    log "Node.js $(node -v 2>/dev/null) meets requirement (>= $min_major)"
    return 0
  fi

  info "Installing Node.js via Termux packages..."

  # Termux provides nodejs-lts which tracks LTS versions
  pkg install -y nodejs-lts 2>/dev/null \
    || apt install -y nodejs-lts 2>/dev/null \
    || {
      # Fallback: regular nodejs
      pkg install -y nodejs 2>/dev/null \
        || apt install -y nodejs 2>/dev/null \
        || {
          warn "Node.js install failed from repos"
          _termux_install_node_binary "$min_major"
          return $?
        }
    }

  # Ensure npm is available
  if ! command -v npm &>/dev/null; then
    pkg install -y npm 2>/dev/null \
      || apt install -y npm 2>/dev/null \
      || true
  fi

  # Verify installation
  if termux_node_meets_requirement "$min_major"; then
    log "Node.js $(node -v) installed"
    return 0
  fi

  warn "Node.js installed but may not meet requirement"
  warn "Current: $(node -v 2>/dev/null || echo 'not found'), need >= v${min_major}"
  return 1
}

termux_node_meets_requirement() {
  local min_major="$1"
  if ! command -v node &>/dev/null; then
    return 1
  fi
  local node_ver
  node_ver=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
  if [ -n "$node_ver" ] && [ "$node_ver" -ge "$min_major" ] 2>/dev/null; then
    return 0
  fi
  return 1
}

_termux_install_node_binary() {
  local min_major="$1"
  local ver="20.19.1"
  local arch
  case "$TERMUX_ARCH" in
    aarch64) arch="arm64" ;;
    armv7l)  arch="armv7l" ;;
    x86_64)  arch="x64" ;;
    *)       arch="arm64" ;;
  esac

  # Termux uses Android's libc (bionic), use the linux binary
  local suffix=""
  # Note: Termux has its own libc; standard glibc binaries may not work.
  # The termux package is preferred. This is a last resort.
  local url="https://nodejs.org/dist/v${ver}/node-v${ver}-linux-${arch}.tar.xz"
  local tmp_dir="/tmp/vplink-node-install-$$"
  mkdir -p "$tmp_dir"

  info "Downloading Node.js v${ver} (linux-${arch})..."
  if ! curl -fsSL --connect-timeout 30 --max-time 300 \
       -o "$tmp_dir/node.tar.xz" "$url"; then
    warn "Download failed: $url"
    rm -rf "$tmp_dir"
    return 1
  fi

  tar -xf "$tmp_dir/node.tar.xz" -C "$tmp_dir" || {
    warn "Extraction failed"
    rm -rf "$tmp_dir"
    return 1
  }

  local extract_dir
  extract_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "node-v*" | head -1)
  if [ -z "$extract_dir" ]; then
    warn "Could not find extracted Node.js directory"
    rm -rf "$tmp_dir"
    return 1
  fi

  mkdir -p "$PREFIX/bin"
  cp "$extract_dir/bin/node" "$PREFIX/bin/node" 2>/dev/null || {
    warn "Failed to copy Node.js binary"
    rm -rf "$tmp_dir"
    return 1
  }

  # Also copy npm/npx
  for bin_name in npm npx corepack; do
    if [ -f "$extract_dir/bin/$bin_name" ]; then
      cp "$extract_dir/bin/$bin_name" "$PREFIX/bin/$bin_name" 2>/dev/null || true
      chmod +x "$PREFIX/bin/$bin_name" 2>/dev/null || true
    fi
  done

  rm -rf "$tmp_dir"

  if termux_node_meets_requirement "$min_major"; then
    log "Node.js v${ver} installed to $PREFIX/bin"
    return 0
  fi

  warn "Node.js binary installed but may not work on Termux (bionic libc)"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  Chromium
# ───────────────────────────────────────────────────────────────

termux_install_chromium() {
  set -euo pipefail

  if ! termux_is_termux; then
    warn "Not running in Termux — skipping"
    return 1
  fi

  # Check if already installed
  if command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null; then
    log "Chromium already installed: $(command -v chromium-browser || command -v chromium)"
    return 0
  fi

  # Ensure x11-repo is available (chromium is in x11-repo)
  _termux_ensure_x11_repo

  info "Installing Chromium..."
  pkg install -y chromium 2>/dev/null \
    || apt install -y chromium 2>/dev/null \
    || {
      warn "chromium package not available"
      warn "Try: pkg install x11-repo && pkg install chromium"
      return 1
    }

  if command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null; then
    log "Chromium installed"
    return 0
  fi

  warn "Chromium installation may have failed"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  X11 / Xvfb Setup
# ───────────────────────────────────────────────────────────────

termux_setup_x11() {
  set -euo pipefail

  if ! termux_is_termux; then
    warn "Not running in Termux — skipping"
    return 1
  fi

  info "Setting up X11 environment..."

  # Ensure x11-repo is enabled
  _termux_ensure_x11_repo

  # Install X11 packages
  local x11_pkgs=(
    x11-repo
    termux-x11-nightly
    tigervnc
    xorg-xrandr
    xorg-xset
  )

  for pkg_name in "${x11_pkgs[@]}"; do
    if ! pkg list-installed 2>/dev/null | grep -q "^${pkg_name}/"; then
      pkg install -y "$pkg_name" 2>/dev/null || true
    fi
  done

  # Install Xvfb for headless display (if available in repos)
  pkg install -y xorg-xvfb 2>/dev/null \
    || pkg install -y xvfb 2>/dev/null \
    || {
      # Termux may not have Xvfb — use Xvnc or termux-x11 instead
      warn "Xvfb not available in Termux repos — using alternative"
    }

  # Create a wrapper script for starting X display
  local bin_dir="${PREFIX:-/data/data/com.termux/files/usr}/bin"
  mkdir -p "$bin_dir"

  cat > "$bin_dir/vplink-x11-start" << 'X11START'
#!/data/data/com.termux/files/usr/bin/bash
# Start X11 display for VPLink on Termux

DISPLAY_NUM="${1:-99}"
export DISPLAY=":$DISPLAY_NUM"

# Try termux-x11 first
if command -v termux-x11 &>/dev/null; then
  termux-x11 :$DISPLAY_NUM &
  sleep 2
  echo "Termux X11 started on $DISPLAY"
  return 0 2>/dev/null || exit 0
fi

# Try VNC
if command -v Xvnc &>/dev/null; then
  Xvnc "$DISPLAY" -geometry 1920x1080 -depth 24 -SecurityTypes=None &
  sleep 1
  echo "VNC X11 started on $DISPLAY"
  return 0 2>/dev/null || exit 0
fi

echo "No X11 server available"
exit 1
X11START

  chmod +x "$bin_dir/vplink-x11-start"

  # Create stop script
  cat > "$bin_dir/vplink-x11-stop" << 'X11STOP'
#!/data/data/com.termux/files/usr/bin/bash
# Stop X11 display for VPLink on Termux

pkill -f "Xvnc|Xvfb|termux-x11" 2>/dev/null || true
echo "X11 display stopped"
X11STOP

  chmod +x "$bin_dir/vplink-x11-stop"

  log "X11 environment configured"
  info "Start X11: vplink-x11-start"
  info "Stop X11:  vplink-x11-stop"
}

_termux_ensure_x11_repo() {
  # Check if x11-repo is already enabled
  if pkg list-repo 2>/dev/null | grep -q "x11-repo"; then
    return 0
  fi

  # Also check for packages.x86.dev (new repo structure)
  if [ -d "$PREFIX/etc/apt/sources.list.d" ] 2>/dev/null; then
    if ls "$PREFIX/etc/apt/sources.list.d/"*x11* 2>/dev/null; then
      return 0
    fi
  fi

  info "Enabling x11-repo..."
  pkg install -y x11-repo 2>/dev/null || {
    # Manual setup: add x11-repo
    local repo_url="https://packages.termux.dev/x11"
    local gpg_url="https://packages.termux.dev/x11/gpg"
    local sources_file="$PREFIX/etc/apt/sources.list.d/x11.list"

    mkdir -p "$PREFIX/etc/apt/sources.list.d"

    # Download and install GPG key
    curl -fsSL "$gpg_url" 2>/dev/null \
      | gpg --dearmor -o "$PREFIX/etc/apt/trusted.gpg.d/x11-repo.gpg" 2>/dev/null || true

    # Add repo
    echo "deb $repo_url stable main" > "$sources_file" 2>/dev/null || true

    pkg update -y 2>/dev/null || apt update -y 2>/dev/null || true
    log "x11-repo enabled manually"
  }
}

# ───────────────────────────────────────────────────────────────
#  Storage permissions
# ───────────────────────────────────────────────────────────────

termux_fix_storage() {
  set -euo pipefail

  if ! termux_is_termux; then
    warn "Not running in Termux — skipping"
    return 1
  fi

  local storage_dir="$HOME/storage"

  # Check if already granted
  if [ -d "$storage_dir" ] && [ -d "$storage_dir/downloads" ] 2>/dev/null; then
    log "Storage permissions already granted"
    return 0
  fi

  info "Requesting storage permissions..."
  info "You may see a system dialog — please tap 'Allow'."

  termux-setup-storage 2>/dev/null || {
    warn "termux-setup-storage failed"
    warn "Try running manually: termux-setup-storage"
    warn "Or grant storage permission in Android Settings > Apps > Termux > Permissions"
    return 1
  }

  # Wait for user to grant permission
  local retries=0
  while [ $retries -lt 10 ]; do
    if [ -d "$storage_dir" ]; then
      # Create subdirectories that VPLink might need
      mkdir -p "$storage_dir/downloads" 2>/dev/null || true
      mkdir -p "$storage_dir/documents" 2>/dev/null || true
      mkdir -p "$storage_dir/pictures" 2>/dev/null || true
      log "Storage permissions granted"
      return 0
    fi
    sleep 1
    retries=$((retries + 1))
  done

  warn "Storage permission may not have been granted"
  warn "VPLink will use internal storage at: $HOME"
  return 0
}

# ───────────────────────────────────────────────────────────────
#  LD_PRELOAD workaround
# ───────────────────────────────────────────────────────────────

_termux_setup_ld_preload() {
  # Termux has issues with some Node.js native modules (like libuv)
  # Setting LD_PRELOAD can help resolve some linking issues
  local termux_bashrc="$HOME/.bashrc"

  if grep -q "Added by VPLink" "$termux_bashrc" 2>/dev/null; then
    return 0
  fi

  # Some Termux environments need this for Node.js native addons
  {
    echo ""
    echo "# Added by VPLink — Termux LD_PRELOAD workaround"
    echo 'if [ -f "$PREFIX/lib/libpython3.11.so" ] 2>/dev/null; then'
    echo '  export LD_PRELOAD="$PREFIX/lib/libpython3.11.so${LD_PRELOAD:+:$LD_PRELOAD}"'
    echo 'fi'
  } >> "$termux_bashrc" 2>/dev/null || true

  debug "LD_PRELOAD workaround configured"
}

# ───────────────────────────────────────────────────────────────
#  Cleanup
# ───────────────────────────────────────────────────────────────

termux_cleanup() {
  set -euo pipefail

  if ! termux_is_termux; then
    return 0
  fi

  info "Cleaning up Termux..."

  pkg cache clean 2>/dev/null || apt-get clean 2>/dev/null || true
  rm -rf /tmp/vplink-* 2>/dev/null || true
  rm -rf "$PREFIX/tmp/"* 2>/dev/null || true

  # Clean apt cache
  rm -rf "$PREFIX/var/cache/apt/archives/"*.deb 2>/dev/null || true

  log "Termux cleanup complete"
}

# ───────────────────────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────────────────────

debug() {
  if [ -n "${VPLINK_DEBUG:-}" ]; then
    echo "[DEBUG] $*"
  fi
}

# Source logging helpers if available
if type log &>/dev/null; then
  :  # already sourced
elif [ -f "${BASH_SOURCE[0]%/*}/../logging/logger.sh" ]; then
  # shellcheck disable=SC1091
  source "${BASH_SOURCE[0]%/*}/../logging/logger.sh"
else
  log()   { echo "[OK] $*"; }
  warn()  { echo "[WARN] $*"; }
  fail()  { echo "[FAIL] $*" >&2; }
  info()  { echo "[INFO] $*"; }
  debug() { [ -n "${VPLINK_DEBUG:-}" ] && echo "[DEBUG] $*" || true; }
fi
