#!/usr/bin/env bash
# installer/platforms/macos.sh — macOS-specific installation logic
# Handles Apple Silicon (arm64) and Intel (x86_64) architectures.
# All functions are idempotent (safe to re-run).

# ───────────────────────────────────────────────────────────────
#  Architecture detection
# ───────────────────────────────────────────────────────────────

macos_detect_arch() {
  local arch
  arch=$(uname -m)
  case "$arch" in
    arm64|aarch64)
      echo "arm64"
      BREW_PREFIX="/opt/homebrew"
      ;;
    x86_64|amd64)
      echo "x86_64"
      BREW_PREFIX="/usr/local"
      ;;
    *)
      echo "unknown"
      BREW_PREFIX="/usr/local"
      ;;
  esac
}

macos_is_apple_silicon() {
  [ "$(uname -m)" = "arm64" ]
}

macos_brew_bin() {
  echo "${BREW_PREFIX:-/usr/local}/bin/brew"
}

# ───────────────────────────────────────────────────────────────
#  Homebrew bootstrap
# ───────────────────────────────────────────────────────────────

macos_ensure_brew() {
  if command -v brew &>/dev/null; then
    return 0
  fi

  # Check both possible locations
  if [ -x "${BREW_PREFIX:-/usr/local}/bin/brew" ]; then
    eval "$("${BREW_PREFIX:-/usr/local}/bin/brew" shellenv)" 2>/dev/null || true
    return 0
  fi

  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
    return 0
  fi

  info "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
    warn "Homebrew installation failed"
    return 1
  }

  # Add brew to PATH for this session
  if macos_is_apple_silicon; then
    eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
  else
    eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null || true
  fi

  if command -v brew &>/dev/null; then
    log "Homebrew installed"
    return 0
  fi

  warn "Homebrew installed but not found in PATH"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  Prerequisites
# ───────────────────────────────────────────────────────────────

macos_install_prerequisites() {
  set -euo pipefail

  macos_detect_arch >/dev/null
  macos_ensure_brew || return 1

  info "Updating Homebrew..."
  brew update 2>/dev/null || true

  # Build essentials
  local formulae=(
    curl
    wget
    git
    jq
    make
    gcc
    python@3
    xz
    unzip
  )

  info "Installing base packages via Homebrew..."
  for f in "${formulae[@]}"; do
    if brew list "$f" &>/dev/null 2>&1; then
      debug "  $f already installed"
    else
      info "  Installing $f..."
      brew install "$f" 2>/dev/null || warn "Failed to install $f"
    fi
  done

  # Chromium (cask)
  macos_install_chromium

  log "macOS prerequisites installed"
}

# ───────────────────────────────────────────────────────────────
#  Node.js
# ───────────────────────────────────────────────────────────────

macos_install_node() {
  set -euo pipefail
  local min_major="${1:-18}"

  macos_detect_arch >/dev/null
  macos_ensure_brew || true

  # Check if current node meets requirement
  if macos_node_meets_requirement "$min_major"; then
    log "Node.js $(node -v 2>/dev/null) meets requirement (>= $min_major)"
    return 0
  fi

  # Try nvm first (user-installed)
  if [ -n "${HOME:-}" ] && [ -d "$HOME/.nvm" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh" 2>/dev/null || true
    if command -v nvm &>/dev/null; then
      info "Installing Node.js via nvm..."
      nvm install "$min_major" 2>/dev/null || nvm install node 2>/dev/null || true
      nvm alias default "$min_major" 2>/dev/null || true
      if macos_node_meets_requirement "$min_major"; then
        log "Node.js $(node -v) installed via nvm"
        return 0
      fi
    fi
  fi

  # Try fnm
  if command -v fnm &>/dev/null; then
    info "Installing Node.js via fnm..."
    fnm install "$min_major" 2>/dev/null || true
    fnm use "$min_major" 2>/dev/null || true
    if macos_node_meets_requirement "$min_major"; then
      log "Node.js $(node -v) installed via fnm"
      return 0
    fi
  fi

  # Try Homebrew
  if command -v brew &>/dev/null; then
    info "Installing Node.js via Homebrew..."
    brew install node@${min_major} 2>/dev/null || brew upgrade node@${min_major} 2>/dev/null || true

    # Link if installed as keg-only
    if ! macos_node_meets_requirement "$min_major"; then
      brew link --force --overwrite node@${min_major} 2>/dev/null || true
    fi

    if macos_node_meets_requirement "$min_major"; then
      log "Node.js $(node -v) installed via Homebrew"
      return 0
    fi
  fi

  # Try n package manager
  if command -v npm &>/dev/null; then
    npm install -g n 2>/dev/null || true
    if command -v n &>/dev/null; then
      n "$min_major" 2>/dev/null || true
      if macos_node_meets_requirement "$min_major"; then
        log "Node.js $(node -v) installed via n"
        return 0
      fi
    fi
  fi

  # Direct binary download
  _macos_install_node_binary "$min_major"
}

macos_node_meets_requirement() {
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

_macos_install_node_binary() {
  local min_major="$1"
  local ver="20.19.1"
  local os_arch
  os_arch=$(macos_detect_arch)
  case "$os_arch" in
    arm64) os_arch="arm64" ;;
    *)     os_arch="x64" ;;
  esac

  local url="https://nodejs.org/dist/v${ver}/node-v${ver}-darwin-${os_arch}.tar.xz"
  local tmp_dir="/tmp/vplink-node-install-$$"
  mkdir -p "$tmp_dir"

  info "Downloading Node.js v${ver} for darwin-${os_arch}..."
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

  local install_base="/usr/local"
  if macos_is_apple_silicon; then
    install_base="/opt/homebrew"
  fi

  sudo cp -r "$extract_dir/bin/"* "$install_base/bin/" 2>/dev/null || {
    warn "Failed to copy Node.js binaries"
    rm -rf "$tmp_dir"
    return 1
  }
  sudo cp -r "$extract_dir/lib/"* "$install_base/lib/" 2>/dev/null || true

  rm -rf "$tmp_dir"

  if macos_node_meets_requirement "$min_major"; then
    log "Node.js v${ver} installed to $install_base/bin"
    return 0
  fi

  warn "Node.js binary installed but not found in PATH"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  Chromium
# ───────────────────────────────────────────────────────────────

macos_install_chromium() {
  set -euo pipefail

  # Already available?
  if [ -d "/Applications/Chromium.app" ] \
      || [ -d "$HOME/Applications/Chromium.app" ] \
      || command -v chromium &>/dev/null; then
    log "Chromium already installed"
    return 0
  fi

  macos_ensure_brew || return 1

  info "Installing Chromium via Homebrew..."
  brew install --cask chromium 2>/dev/null || {
    warn "Cask install failed, trying upgrade..."
    brew upgrade --cask chromium 2>/dev/null || true
  }

  if [ -d "/Applications/Chromium.app" ] \
      || [ -d "$HOME/Applications/Chromium.app" ]; then
    log "Chromium installed"
  else
    warn "Chromium installation may have failed — check manually"
  fi
}

# ───────────────────────────────────────────────────────────────
#  Firewall
# ───────────────────────────────────────────────────────────────

macos_setup_firewall() {
  set -euo pipefail

  # Check if we can manage the firewall
  if ! command -v /usr/libexec/ApplicationFirewall/socketfilterfw &>/dev/null; then
    warn "macOS firewall tool not found"
    return 0
  fi

  local fw_tool="/usr/libexec/ApplicationFirewall/socketfilterfw"

  # Check current state
  local fw_state
  fw_state=$($fw_tool --getglobalstate 2>/dev/null || echo "unknown")

  if echo "$fw_state" | grep -qi "disabled"; then
    info "macOS Application Firewall is disabled — no exceptions needed"
    return 0
  fi

  # Check if Node.js is already allowed
  local node_path
  node_path=$(command -v node 2>/dev/null || echo "")
  if [ -n "$node_path" ]; then
    local node_allowed
    node_allowed=$($fw_tool --listapps 2>/dev/null | grep -i "node" || true)
    if [ -n "$node_allowed" ]; then
      log "Node.js already has firewall exception"
      return 0
    fi
  fi

  # Check if running interactively and firewall is blocking
  if [ -t 0 ] && [ -t 1 ]; then
    echo ""
    echo "  macOS Application Firewall is active."
    echo "  VPLink may need network access for automation."
    echo ""
    read -r -p "  Allow Node.js through the firewall? (y/N): " allow_fw
    if [[ ! "$allow_fw" =~ ^[yY]$ ]]; then
      info "Skipping firewall configuration"
      return 0
    fi
  else
    info "Non-interactive mode — skipping firewall configuration"
    info "If needed, run manually: sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/node"
    return 0
  fi

  # Add firewall exception for Node.js
  if [ -n "$node_path" ]; then
    sudo $fw_tool --add "$node_path" 2>/dev/null || true
    sudo $fw_tool --unblockapp "$node_path" 2>/dev/null || true
    log "Firewall exception added for $node_path"
  fi

  # Also add for common node locations on Apple Silicon
  if macos_is_apple_silicon; then
    for alt_path in /opt/homebrew/bin/node /usr/local/bin/node; do
      if [ -x "$alt_path" ]; then
        sudo $fw_tool --add "$alt_path" 2>/dev/null || true
        sudo $fw_tool --unblockapp "$alt_path" 2>/dev/null || true
      fi
    done
  fi

  log "Firewall configured"
}

# ───────────────────────────────────────────────────────────────
#  Cleanup
# ───────────────────────────────────────────────────────────────

macos_cleanup() {
  set -euo pipefail

  info "Cleaning up macOS..."

  # Homebrew cleanup
  if command -v brew &>/dev/null; then
    brew cleanup 2>/dev/null || true
    brew autoremove 2>/dev/null || true
  fi

  # Remove downloaded archives
  rm -rf /tmp/vplink-node-install-* 2>/dev/null || true

  log "macOS cleanup complete"
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
