#!/bin/bash
# VPLink 3.0 — Production-Grade One-Command Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main/install.sh | bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════

REPO="https://github.com/adittaya/VPLINK-3.0"
RAW_BASE="https://raw.githubusercontent.com/adittaya/VPLINK-3.0/main"
INSTALL_VERSION="3.0.0"
MIN_NODE_MAJOR=18
SCRIPT_NAME="vplink3.0"

# Paths
if [ -n "${XDG_CONFIG_HOME:-}" ]; then
  CONFIG_DIR="$XDG_CONFIG_HOME/.vplink3.0"
else
  CONFIG_DIR="$HOME/.vplink3.0"
fi
INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"
LOG_DIR="$CONFIG_DIR/logs"
LOG_FILE="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
STATE_FILE="$CONFIG_DIR/install_state.json"
CREDENTIAL_FILE="$CONFIG_DIR/config.json"

# Colors
if [ -t 1 ]; then
  BOLD='\033[1m'; DIM='\033[2m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
  CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
else
  BOLD=''; DIM=''; GREEN=''; YELLOW=''; CYAN=''; RED=''; NC=''
fi

# ═══════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════

mkdir -p "$LOG_DIR" "$CONFIG_DIR"
touch "$LOG_FILE"

log()   { echo -e "${GREEN}✓${NC} $1"; echo "[$(date +%T)] OK  $1" >> "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; echo "[$(date +%T)] WARN $1" >> "$LOG_FILE"; }
fail()  { echo -e "${RED}✗${NC} $1"; echo "[$(date +%T)] FAIL $1" >> "$LOG_FILE"; }
info()  { echo -e "${CYAN}${1}${NC}"; echo "[$(date +%T)] INFO $1" >> "$LOG_FILE"; }
step()  { echo -e "\n${BOLD}[$1/${TOTAL_STEPS}]${NC} $2"; echo "[$(date +%T)] STEP $1/$TOTAL_STEPS $2" >> "$LOG_FILE"; }
debug() { [ -n "${VPLINK_DEBUG:-}" ] && echo -e "${DIM}$1${NC}"; echo "[$(date +%T)] DEBUG $1" >> "$LOG_FILE"; }

cleanup() {
  local ec=$?
  if [ "$ec" -ne 0 ] && [ "$ec" -ne 130 ]; then
    echo ""
    fail "Installation failed (exit code $ec)"
    info "Log file: $LOG_FILE"
    info "To retry: bash install.sh"
    info "To report: $REPO/issues"
  fi
}
trap cleanup EXIT

# ═══════════════════════════════════════════════════════════════
#  ENVIRONMENT DETECTION
# ═══════════════════════════════════════════════════════════════

detect_os() {
  OS="linux"
  case "$(uname -s)" in
    Darwin) OS="macos" ;;
    Linux)  OS="linux" ;;
    *)      OS="unknown" ;;
  esac
}

detect_distro() {
  DISTRO="unknown"
  DISTRO_FAMILY="unknown"
  PKG_MANAGER=""
  PKG_UPDATE=""
  PKG_INSTALL=""
  PKG_QUERY=""

  # Termux
  if [ -n "${PREFIX:-}" ] && [ -d /data/data/com.termux ] 2>/dev/null; then
    DISTRO="termux"
    DISTRO_FAMILY="termux"
    PKG_MANAGER="pkg"
    PKG_UPDATE="pkg update -y"
    PKG_INSTALL="pkg install -y"
    PKG_QUERY="pkg list-installed"
    return
  fi

  # proot-distro
  if [ -f /etc/proot-distro ] || [ -n "${PROOT_ROOT:-}" ] || [ -f "/.proot" ] 2>/dev/null; then
    DISTRO_FAMILY="proot"
  fi

  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO="${ID,,}"
    local id_like="${ID_LIKE:-$ID}"
    DISTRO_FAMILY="${id_like,,}"
  elif command -v lsb_release &>/dev/null; then
    DISTRO="$(lsb_release -si | tr '[:upper:]' '[:lower:]')"
  fi

  # Normalize
  case "$DISTRO" in
    debian|ubuntu|kali|linuxmint|raspbian|pop|elementary|zorin)
      DISTRO_FAMILY="debian"
      PKG_MANAGER="apt-get"
      PKG_UPDATE="apt-get update -qq"
      PKG_INSTALL="apt-get install -y -qq"
      PKG_QUERY="dpkg -s"
      ;;
    arch|manjaro|endeavouros|artix|garuda)
      DISTRO_FAMILY="arch"
      PKG_MANAGER="pacman"
      PKG_UPDATE="pacman -Sy --noconfirm"
      PKG_INSTALL="pacman -S --noconfirm"
      PKG_QUERY="pacman -Qi"
      ;;
    fedora|rocky|almalinux|centos|rhel)
      DISTRO_FAMILY="fedora"
      PKG_MANAGER="dnf"
      PKG_UPDATE="dnf check-update -q || true"
      PKG_INSTALL="dnf install -y"
      PKG_QUERY="rpm -q"
      ;;
    opensuse*|suse)
      DISTRO_FAMILY="suse"
      PKG_MANAGER="zypper"
      PKG_UPDATE="zypper refresh"
      PKG_INSTALL="zypper install -y"
      PKG_QUERY="rpm -q"
      ;;
    alpine)
      DISTRO_FAMILY="alpine"
      PKG_MANAGER="apk"
      PKG_UPDATE="apk update -q"
      PKG_INSTALL="apk add -q"
      PKG_QUERY="apk info -e"
      ;;
    *)
      # Fallback: detect by package manager
      for pm in apt-get apt dnf yum pacman zypper apk; do
        if command -v "$pm" &>/dev/null; then
          case "$pm" in
            apt-get|apt) DISTRO_FAMILY="debian"; PKG_MANAGER="apt-get"; PKG_UPDATE="apt-get update -qq"; PKG_INSTALL="apt-get install -y -qq"; PKG_QUERY="dpkg -s" ;;
            dnf) DISTRO_FAMILY="fedora"; PKG_MANAGER="dnf"; PKG_UPDATE="dnf check-update -q || true"; PKG_INSTALL="dnf install -y"; PKG_QUERY="rpm -q" ;;
            yum) DISTRO_FAMILY="fedora"; PKG_MANAGER="yum"; PKG_UPDATE="yum check-update -q || true"; PKG_INSTALL="yum install -y"; PKG_QUERY="rpm -q" ;;
            pacman) DISTRO_FAMILY="arch"; PKG_MANAGER="pacman"; PKG_UPDATE="pacman -Sy --noconfirm"; PKG_INSTALL="pacman -S --noconfirm"; PKG_QUERY="pacman -Qi" ;;
            zypper) DISTRO_FAMILY="suse"; PKG_MANAGER="zypper"; PKG_UPDATE="zypper refresh"; PKG_INSTALL="zypper install -y"; PKG_QUERY="rpm -q" ;;
            apk) DISTRO_FAMILY="alpine"; PKG_MANAGER="apk"; PKG_UPDATE="apk update -q"; PKG_INSTALL="apk add -q"; PKG_QUERY="apk info -e" ;;
          esac
          break
        fi
      done
      ;;
  esac

  # Fallback for distros not matched above
  if [ -z "$PKG_MANAGER" ]; then
    if command -v zypper &>/dev/null; then
      DISTRO_FAMILY="suse"; PKG_MANAGER="zypper"; PKG_UPDATE="zypper refresh"; PKG_INSTALL="zypper install -y"; PKG_QUERY="rpm -q"
    elif command -v apk &>/dev/null; then
      DISTRO_FAMILY="alpine"; PKG_MANAGER="apk"; PKG_UPDATE="apk update -q"; PKG_INSTALL="apk add -q"; PKG_QUERY="apk info -e"
    fi
  fi
  return 0
}

detect_arch() {
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    armv7l|armhf) ARCH="armv7l" ;;
    *) ARCH="unknown" ;;
  esac
}

detect_libc() {
  if command -v ldd &>/dev/null; then
    if ldd --version 2>&1 | grep -qi musl; then
      echo "musl"
    else
      echo "glibc"
    fi
  elif command -v apk &>/dev/null; then
    echo "musl"
  else
    echo "glibc"
  fi
}

is_root() { [ "$(id -u)" -eq 0 ]; }

is_docker() {
  [ -f /.dockerenv ] || (grep -q docker /proc/1/cgroup 2>/dev/null) || [ -n "${DOCKER_CONTAINER:-}" ]
}

is_wsl() {
  grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]
}

is_ci() {
  [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ] || [ -n "${GITLAB_CI:-}" ] || [ -n "${JENKINS_URL:-}" ]
}

is_termux() {
  [ -n "${PREFIX:-}" ] && [ -d /data/data/com.termux ] 2>/dev/null
}

has_cmd() { command -v "$1" &>/dev/null; }

# Global variables (initialized)
# shellcheck disable=SC2034
DISTRO="" && DISTRO_FAMILY="" && ARCH="" && PKG_MANAGER="" && PKG_UPDATE="" && PKG_INSTALL="" && PKG_QUERY="" && OS=""

SUDO=""
if ! is_root && ! is_termux; then
  SUDO="sudo"
fi

# ═══════════════════════════════════════════════════════════════
#  STATE MANAGEMENT (idempotency)
# ═══════════════════════════════════════════════════════════════

STATE_SYS_DEPS=""
STATE_NODE=""
STATE_NPM_DEPS=""
STATE_PLAYWRIGHT=""
STATE_CMD=""
STATE_CREDENTIALS=""

load_state() {
  [ -f "$STATE_FILE" ] || return 0
  local s
  s=$(cat "$STATE_FILE")
  # Portable extraction — no grep -oP (not available on macOS)
  STATE_SYS_DEPS=$(echo "$s" | sed -n 's/.*"sys_deps"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_NODE=$(echo "$s" | sed -n 's/.*"node"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_NPM_DEPS=$(echo "$s" | sed -n 's/.*"npm_deps"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_PLAYWRIGHT=$(echo "$s" | sed -n 's/.*"playwright"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_CMD=$(echo "$s" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_CREDENTIALS=$(echo "$s" | sed -n 's/.*"credentials"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
}

save_state() {
  mkdir -p "$(dirname "$STATE_FILE")"
  cat > "$STATE_FILE" <<EOF
{
  "sys_deps": "${STATE_SYS_DEPS:-done}",
  "node": "${STATE_NODE:-done}",
  "npm_deps": "${STATE_NPM_DEPS:-done}",
  "playwright": "${STATE_PLAYWRIGHT:-done}",
  "command": "${STATE_CMD:-done}",
  "credentials": "${STATE_CREDENTIALS:-pending}",
  "version": "$INSTALL_VERSION",
  "updated": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}

mark_done() { save_state; }
clear_state() { rm -f "$STATE_FILE"; }

# ═══════════════════════════════════════════════════════════════
#  SYSTEM DEPENDENCIES
# ═══════════════════════════════════════════════════════════════

install_system_deps() {
  [ "$STATE_SYS_DEPS" = "done" ] && { log "System dependencies already installed"; return 0; }

  debug "Installing system dependencies (distro=$DISTRO, family=$DISTRO_FAMILY)"

  if [ "$DISTRO_FAMILY" = "termux" ]; then
    pkg update -y
    pkg install -y curl git nodejs-lts chromium x11-repo || true
  elif [ "$DISTRO_FAMILY" = "debian" ]; then
    $SUDO apt-get update -qq 2>/dev/null || warn "apt-get update failed — using cache"
    $SUDO apt-get install -y -qq curl git xvfb x11vnc jq chromium-browser \
      libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
      libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
      libasound2t64 ca-certificates || \
    $SUDO apt-get install -y -qq curl git xvfb x11vnc jq chromium-browser \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
      libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
      libasound2 ca-certificates || \
    warn "Some Debian packages failed — proceeding"
  elif [ "$DISTRO_FAMILY" = "arch" ]; then
    $SUDO pacman -Sy --noconfirm curl git xorg-server-xvfb x11vnc jq \
      nss nspr atk at-spi2-atk cups libdrm dbus libxkbcommon \
      libxcomposite libxdamage libxfixes libxrandr libgbm pango cairo alsa-lib \
      ca-certificates || warn "Some Arch packages failed — proceeding"
  elif [ "$DISTRO_FAMILY" = "fedora" ]; then
    $SUDO dnf install -y curl git xorg-x11-server-Xvfb x11vnc jq \
      nss nspr atk at-spi2-atk cups-libs libdrm dbus-libs libxkbcommon \
      libXcomposite libXdamage libXfixes libXrandr libgbm pango cairo alsa-lib \
      ca-certificates || warn "Some Fedora packages failed — proceeding"
  elif [ "$DISTRO_FAMILY" = "suse" ]; then
    $SUDO zypper install -y curl git xvfb x11vnc jq \
      nss nspr atk at-spi2-atk cups-libs libdrm dbus-1 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
      pango cairo alsa-lib ca-certificates || warn "Some SUSE packages failed — proceeding"
  elif [ "$DISTRO_FAMILY" = "alpine" ]; then
    $SUDO apk add curl git xvfb x11vnc jq \
      nss nspr atk at-spi2-atk cups-libs libdrm dbus libxkbcommon \
      libxcomposite libxdamage libxfixes libxrandr libgbm pango cairo alsa-lib \
      ca-certificates || warn "Some Alpine packages failed — proceeding"
  else
    warn "Unknown distro. Attempting package install..."
    # Try every known package manager
    for pm_install in \
      "apt-get apt-get install -y -qq" \
      "dnf dnf install -y" \
      "pacman pacman -S --noconfirm" \
      "zypper zypper install -y" \
      "apk apk add"
    do
      pm=$(echo "$pm_install" | cut -d' ' -f1)
      cmd=$(echo "$pm_install" | cut -d' ' -f2-)
      if command -v "$pm" &>/dev/null; then
        info "Using $pm to install base packages..."
        $SUDO $cmd curl git ca-certificates jq 2>/dev/null || true
        break
      fi
    done
  fi

  STATE_SYS_DEPS="done"
  log "System dependencies installed"
}

# ═══════════════════════════════════════════════════════════════
#  NODE.JS MANAGEMENT
# ═══════════════════════════════════════════════════════════════

install_node() {
  [ "$STATE_NODE" = "done" ] && { log "Node.js already installed"; return 0; }

  if has_cmd node; then
    local node_ver
    node_ver=$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)
    if [ "$node_ver" -ge "$MIN_NODE_MAJOR" ] 2>/dev/null; then
      log "Node.js $(node -v) meets requirement (>= $MIN_NODE_MAJOR)"
      STATE_NODE="done"
      return 0
    else
      warn "Node.js $(node -v) is too old (need >= $MIN_NODE_MAJOR), upgrading..."
    fi
  fi

  if is_termux; then
    pkg install -y nodejs-lts
  elif is_root; then
    # Root: use package manager or direct download
    install_node_pkg
  elif [ -d "$HOME/.nvm" ]; then
    # nvm available
    [ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh"
    nvm install "$MIN_NODE_MAJOR" 2>/dev/null || nvm install node
    nvm alias default "$MIN_NODE_MAJOR" 2>/dev/null || true
  elif has_cmd npm && has_cmd n; then
    n "$MIN_NODE_MAJOR"
  else
    # Download binary directly
    install_node_binary
  fi

  if has_cmd node; then
    log "Node.js $(node -v) installed"
    STATE_NODE="done"
  else
    fail "Node.js installation failed"
    return 1
  fi
}

install_node_pkg() {
  case "$DISTRO_FAMILY" in
    debian)
      if ! has_cmd node || [ "$(node -v | sed 's/v//' | cut -d. -f1)" -lt "$MIN_NODE_MAJOR" ]; then
        $SUDO apt-get install -y -qq nodejs 2>/dev/null || {
          curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO bash -
          $SUDO apt-get install -y -qq nodejs
        }
        # Debian may install /usr/bin/nodejs without /usr/bin/node
        if ! has_cmd node && has_cmd nodejs; then
          $SUDO ln -sf /usr/bin/nodejs /usr/local/bin/node
        fi
      fi
      ;;
    fedora) $SUDO dnf module install -y nodejs:20/common 2>/dev/null || $SUDO dnf install -y nodejs ;;
    arch) $SUDO pacman -S --noconfirm nodejs npm ;;
    suse) $SUDO zypper install -y nodejs20 2>/dev/null || $SUDO zypper install -y nodejs ;;
    alpine) $SUDO apk add nodejs npm ;;
    *) install_node_binary ;;
  esac
}

install_node_binary() {
  local ver="20.19.1"
  local arch="$ARCH"
  case "$arch" in
    x86_64) arch="x64" ;;
    aarch64) arch="arm64" ;;
    armv7l) arch="armv7l" ;;
    *) arch="x64" ;;
  esac

  local os="linux"
  [ "$(uname -s)" = "Darwin" ] && os="darwin"
  [ "$DISTRO_FAMILY" = "alpine" ] && os="linux" && ver="${ver}-musl"

  local url="https://nodejs.org/dist/v${ver}/node-v${ver}-${os}-${arch}.tar.xz"
  local tmp_dir="/tmp/node-install-$$"
  mkdir -p "$tmp_dir"

  info "Downloading Node.js v${ver} for ${os}-${arch}..."
  if has_cmd curl; then
    curl -fsSL "$url" -o "$tmp_dir/node.tar.xz" || { fail "Download failed: $url"; rm -rf "$tmp_dir"; return 1; }
  else
    wget -qO "$tmp_dir/node.tar.xz" "$url" || { fail "Download failed: $url"; rm -rf "$tmp_dir"; return 1; }
  fi

  # Verify download is not empty/corrupt
  if [ ! -s "$tmp_dir/node.tar.xz" ]; then
    fail "Downloaded file is empty"
    rm -rf "$tmp_dir"
    return 1
  fi

  tar -xf "$tmp_dir/node.tar.xz" -C "$tmp_dir" || { fail "Extraction failed — corrupt download?"; rm -rf "$tmp_dir"; return 1; }
  $SUDO cp -r "$tmp_dir/node-v${ver}-${os}-${arch}/bin/"* /usr/local/bin/ || { fail "Failed to install Node.js binaries"; rm -rf "$tmp_dir"; return 1; }
  $SUDO cp -r "$tmp_dir/node-v${ver}-${os}-${arch}/lib/"* /usr/local/lib/ 2>/dev/null || true
  rm -rf "$tmp_dir"
  log "Node.js v${ver} installed to /usr/local/bin"
}

install_npm_deps() {
  [ "$STATE_NPM_DEPS" = "done" ] && [ -d "$INSTALL_DIR/node_modules" ] && { log "npm dependencies already installed"; return 0; }

  cd "$INSTALL_DIR" 2>/dev/null || { warn "Project directory missing, skipping npm install"; return 0; }
  info "Installing npm dependencies..."
  npm install --no-audit --no-fund --timeout=60000 2>&1 | tail -3 >> "$LOG_FILE" || {
    warn "npm install failed, retrying with cache clean..."
    npm cache clean --force 2>/dev/null || true
    npm install --no-audit --no-fund --timeout=120000 >> "$LOG_FILE" 2>&1 || {
      warn "npm install failed twice — will try at runtime"
      return 0
    }
  }

  if [ -d "$INSTALL_DIR/node_modules" ]; then
    STATE_NPM_DEPS="done"
    log "npm dependencies installed"
  else
    warn "node_modules missing after install — will try at runtime"
  fi
}

install_playwright() {
  [ "$STATE_PLAYWRIGHT" = "done" ] && { log "Playwright browsers already installed"; return 0; }

  cd "$INSTALL_DIR" 2>/dev/null || { warn "Project directory missing, skipping Playwright install"; return 0; }
  if is_termux; then
    log "Termux: using system Chromium, skipping Playwright browser install"
    STATE_PLAYWRIGHT="done"
    return 0
  fi

  info "Installing Playwright Chromium browser..."
  npx playwright install chromium 2>&1 | tail -5 >> "$LOG_FILE" || {
    warn "Playwright install failed, retrying..."
    npx playwright install chromium >> "$LOG_FILE" 2>&1 || true
  }

  # Verify chromium was actually downloaded
  local pw_chromium
  pw_chromium=$(ls "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1 || true)
  if [ -n "$pw_chromium" ]; then
    STATE_PLAYWRIGHT="done"
    log "Playwright Chromium ready: $pw_chromium"
  else
    # Fallback: check system chromium
    if command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null || command -v google-chrome &>/dev/null; then
      STATE_PLAYWRIGHT="done"
      log "Playwright Chromium not found, but system browser available"
    else
      warn "Playwright Chromium NOT found — will retry on first run"
      STATE_PLAYWRIGHT="pending"
    fi
  fi
}

# ═══════════════════════════════════════════════════════════════
#  PROJECT SETUP
# ═══════════════════════════════════════════════════════════════

setup_project() {
  if [ -d "$INSTALL_DIR" ]; then
    info "Project directory exists at $INSTALL_DIR"
    if [ -d "$INSTALL_DIR/.git" ]; then
      cd "$INSTALL_DIR"
      if ! git diff --quiet 2>/dev/null; then
        warn "Local changes detected — stashing..."
        git stash --include-untracked 2>/dev/null || true
      fi
      info "Updating existing installation..."
      git pull --ff-only 2>&1 | tail -2 >> "$LOG_FILE" || {
        warn "Git pull failed, trying fetch+reset..."
        git fetch origin >> "$LOG_FILE" 2>&1 || {
          fail "Network error — cannot fetch updates"
          return 1
        }
        git reset --hard origin/main 2>/dev/null || git reset --hard HEAD || true
      }
    else
      warn "Directory exists but not a git repo — will use as-is"
    fi
  else
    info "Cloning repository..."
    git clone --depth=1 "$REPO" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1 || {
      fail "Failed to clone repository — check network and try again"
      return 1
    }
  fi
  if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR"
    log "Project ready at $INSTALL_DIR"
  else
    fail "Project directory missing at $INSTALL_DIR after setup"
    return 1
  fi
}

# ═══════════════════════════════════════════════════════════════
#  GLOBAL COMMAND
# ═══════════════════════════════════════════════════════════════

create_global_command() {
  [ "$STATE_CMD" = "done" ] && has_cmd "$SCRIPT_NAME" && { log "Global command $SCRIPT_NAME already installed"; return 0; }

  local launcher="$INSTALL_DIR/vplink3.0.sh"
  local desktop_launcher="$INSTALL_DIR/vplink-desktop.sh"

  chmod +x "$launcher" "$desktop_launcher" 2>/dev/null || true

  if is_root; then
    $SUDO ln -sf "$launcher" "/usr/local/bin/$SCRIPT_NAME"
    $SUDO ln -sf "$desktop_launcher" "/usr/local/bin/vplink-desktop" 2>/dev/null || true
    log "Symlinked $SCRIPT_NAME to /usr/local/bin/"
  elif is_termux; then
    ln -sf "$launcher" "$PREFIX/bin/$SCRIPT_NAME"
    ln -sf "$desktop_launcher" "$PREFIX/bin/vplink-desktop" 2>/dev/null || true
    log "Symlinked $SCRIPT_NAME to $PREFIX/bin/"
  else
    mkdir -p "$HOME/.local/bin"
    ln -sf "$launcher" "$HOME/.local/bin/$SCRIPT_NAME"
    ln -sf "$desktop_launcher" "$HOME/.local/bin/vplink-desktop" 2>/dev/null || true
    log "Symlinked $SCRIPT_NAME to ~/.local/bin/"

    # Ensure ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
      local rcfile="$HOME/.bashrc"
      [ -f "$HOME/.zshrc" ] && rcfile="$HOME/.zshrc"
      [ -f "$HOME/.profile" ] && rcfile="$HOME/.profile"
      echo "" >> "$rcfile"
      echo "# Added by VPLink 3.0 installer" >> "$rcfile"
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rcfile"
      warn "Added ~/.local/bin to PATH in $rcfile — restart shell or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
  fi

  STATE_CMD="done"
  log "Global command $SCRIPT_NAME created"
}

# ═══════════════════════════════════════════════════════════════
#  CREDENTIAL SETUP (first-time only, permanently saved)
# ═══════════════════════════════════════════════════════════════

setup_credentials() {
  # Skip if already configured (credentials exist and are valid)
  if [ -f "$CREDENTIAL_FILE" ]; then
    local cfg
    cfg=$(cat "$CREDENTIAL_FILE" 2>/dev/null || echo '{}')
    local sb_url sb_key
    sb_url=$(echo "$cfg" | grep -o '"supabase_url"[^,]*' | grep -oP ':"[^"]*"' | tr -d '"' || true)
    sb_key=$(echo "$cfg" | grep -o '"supabase_key"[^,]*' | grep -oP ':"[^"]*"' | tr -d '"' || true)
    if [ -n "$sb_url" ] && [ -n "$sb_key" ] && [ "$sb_url" != "''" ] && [ "$sb_key" != "''" ]; then
      STATE_CREDENTIALS="done"
      log "Credentials already configured"
      return 0
    fi
  fi

  # Non-interactive mode: skip with warning
  if [ -n "${VPLINK_NONINTERACTIVE:-}" ] || [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    warn "Non-interactive mode — skipping credential setup. Configure later: vplink3.0 config"
    STATE_CREDENTIALS="skipped"
    return 0
  fi

  # Check if stdin is a terminal (interactive)
  if [ ! -t 0 ]; then
    warn "No interactive terminal — skipping credential setup. Configure later: vplink3.0 config"
    STATE_CREDENTIALS="skipped"
    return 0
  fi

  echo ""
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║              First-Time Credential Setup                ║"
  echo "║                                                        ║"
  echo "║  VPLink uses Supabase for proxy rotation.              ║"
  echo "║  Enter your Supabase credentials below (saved to       ║"
  echo "║  ~/.vplink3.0/config.json with 600 permissions).       ║"
  echo "║                                                        ║"
  echo "║  Leave blank to skip (proxy feature will be disabled).  ║"
  echo "╚══════════════════════════════════════════════════════════╝"
  echo ""

  read -r -p "  Supabase URL [https://bytemjjijgwwcrxlgutf.supabase.co]: " SB_URL
  SB_URL="${SB_URL:-https://bytemjjijgwwcrxlgutf.supabase.co}"

  read -r -p "  Supabase Anon/Publishable Key: " SB_KEY
  read -r -s -p "  Supabase Secret/Service Key (hidden): " SB_SECRET
  echo ""

  # Save credentials
  mkdir -p "$CONFIG_DIR"
  if [ -n "$SB_KEY" ]; then
    cat > "$CREDENTIAL_FILE" <<EOF
{
  "supabase_url": "${SB_URL}",
  "supabase_key": "${SB_KEY}",
  "supabase_secret": "${SB_SECRET}",
  "proxy_enabled": true,
  "proxy_tier": "premium",
  "youtube_traffic": false,
  "mobile_profile": false,
  "random_urls": [],
  "vnc_port": 5900,
  "views": 1
}
EOF
    chmod 600 "$CREDENTIAL_FILE"
    STATE_CREDENTIALS="done"
    log "Credentials saved to $CREDENTIAL_FILE"
  else
    # Save default (disabled proxy)
    cat > "$CREDENTIAL_FILE" <<EOF
{
  "supabase_url": "${SB_URL}",
  "supabase_key": "",
  "supabase_secret": "",
  "proxy_enabled": false,
  "proxy_tier": "premium",
  "youtube_traffic": false,
  "mobile_profile": false,
  "random_urls": [],
  "vnc_port": 5900,
  "views": 1
}
EOF
    chmod 600 "$CREDENTIAL_FILE"
    STATE_CREDENTIALS="skipped"
    warn "Proxy credentials not provided — proxy feature disabled"
  fi
}

# ═══════════════════════════════════════════════════════════════
#  VERIFICATION
# ═══════════════════════════════════════════════════════════════

verify_installation() {
  local errors=0

  # 1. Global command
  if has_cmd "$SCRIPT_NAME"; then
    log "Command $SCRIPT_NAME is globally accessible"
    # Verify it's a valid symlink/file
    local cmd_path
    cmd_path=$(command -v "$SCRIPT_NAME" 2>/dev/null || true)
    if [ -n "$cmd_path" ] && [ ! -f "$cmd_path" ]; then
      warn "Command $SCRIPT_NAME points to missing file: $cmd_path"
      errors=$((errors + 1))
    fi
  else
    fail "$SCRIPT_NAME not found in PATH"
    errors=$((errors + 1))
  fi

  # 2. Node.js
  if has_cmd node; then
    local node_ver
    node_ver=$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)
    if [ "$node_ver" -ge "$MIN_NODE_MAJOR" ] 2>/dev/null; then
      log "Node.js $(node -v) meets requirement (>= $MIN_NODE_MAJOR)"
    else
      warn "Node.js $(node -v) installed but too old (need >= $MIN_NODE_MAJOR)"
      errors=$((errors + 1))
    fi
  else
    fail "Node.js not found"
    errors=$((errors + 1))
  fi

  # 3. Project files
  local required_files=(
    "$INSTALL_DIR/automation.js"
    "$INSTALL_DIR/config.js"
    "$INSTALL_DIR/proxy-rotator.js"
    "$INSTALL_DIR/profile-generator.js"
    "$INSTALL_DIR/vplink3.0.sh"
    "$INSTALL_DIR/vplink-desktop.sh"
    "$INSTALL_DIR/package.json"
  )
  for f in "${required_files[@]}"; do
    if [ -f "$f" ]; then
      log "Found $(basename "$f")"
    else
      fail "Missing: $f"
      errors=$((errors + 1))
    fi
  done

  # 4. node_modules
  if [ -d "$INSTALL_DIR/node_modules" ]; then
    local pkg_count
    pkg_count=$(ls -1 "$INSTALL_DIR/node_modules" 2>/dev/null | wc -l)
    log "npm dependencies installed ($pkg_count packages)"
  else
    warn "node_modules missing — run: cd $INSTALL_DIR && npm install"
    errors=$((errors + 1))
  fi

  # 5. Chromium browser
  local chromium_bin=""
  if is_termux; then
    chromium_bin=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null || echo "")
  else
    # Check Playwright bundled first, then system browsers
    chromium_bin=$(ls "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1 || true)
    if [ -z "$chromium_bin" ]; then
      chromium_bin=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null || command -v google-chrome 2>/dev/null || echo "")
    fi
  fi
  if [ -n "$chromium_bin" ]; then
    log "Chromium found: $chromium_bin"
  else
    warn "Chromium not found — Playwright will attempt to download on first run"
  fi

  # 6. Credentials
  if [ -f "$CREDENTIAL_FILE" ]; then
    log "Config file exists ($CREDENTIAL_FILE)"
  else
    warn "Config file missing — run: vplink3.0 config to set up"
  fi

  # 7. State file
  if [ -f "$STATE_FILE" ]; then
    log "Install state file present"
  else
    warn "Install state file missing — re-run: bash install.sh"
  fi

  return $errors
}

# ═══════════════════════════════════════════════════════════════
#  UNINSTALL
# ═══════════════════════════════════════════════════════════════

uninstall() {
  echo ""
  echo "╔══════════════════════════════════════════════╗"
  echo "║        VPLink 3.0 — Uninstall               ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""

  local remove_all="${1:-false}"

  # Check for running VPLink processes first
  local running_pids
  running_pids=$(pgrep -f "node.*automation.js\|vplink3.0" 2>/dev/null | grep -v "^$$\$" || true)
  if [ -n "$running_pids" ]; then
    warn "VPLink processes are running (PIDs: $running_pids)"
    if [ -t 0 ]; then
      read -r -p "Kill running processes before uninstall? (y/N): " kill_procs
      if [[ "$kill_procs" =~ ^[yY] ]]; then
        echo "$running_pids" | xargs -r kill 2>/dev/null || true
        sleep 1
        # Force kill if still alive
        running_pids=$(pgrep -f "node.*automation.js\|vplink3.0" 2>/dev/null | grep -v "^$$\$" || true)
        if [ -n "$running_pids" ]; then
          echo "$running_pids" | xargs -r kill -9 2>/dev/null || true
        fi
        log "Processes terminated"
      fi
    else
      warn "Non-interactive mode — killing processes"
      echo "$running_pids" | xargs -r kill 2>/dev/null || true
      sleep 1
    fi
  fi

  # Remove global commands
  for cmd in vplink3.0 vplink-desktop; do
    for loc in "/usr/local/bin/$cmd" "$HOME/.local/bin/$cmd" "${PREFIX:-/data/data/com.termux/files/usr}/bin/$cmd"; do
      if [ -f "$loc" ] || [ -L "$loc" ]; then
        rm -f "$loc" && info "Removed $loc"
      fi
    done
  done

  # Remove project directory
  if [ -d "$INSTALL_DIR" ]; then
    if [ "$remove_all" = "true" ]; then
      rm -rf "$INSTALL_DIR"
      log "Removed project directory: $INSTALL_DIR"
    else
      warn "Keeping project directory: $INSTALL_DIR"
      info "To remove manually: rm -rf $INSTALL_DIR"
    fi
  fi

  # Remove config (auto-remove in non-interactive/CI, prompt otherwise)
  if [ -d "$CONFIG_DIR" ] && [ "$remove_all" = "true" ]; then
    local remove_cfg="n"
    if [ -n "${VPLINK_NONINTERACTIVE:-}" ] || [ -n "${CI:-}" ]; then
      remove_cfg="y"
    elif [ -t 0 ]; then
      read -r -p "Remove configuration and credentials? (y/N): " remove_cfg
    fi
    if [[ "$remove_cfg" =~ ^[yY] ]]; then
      rm -rf "$CONFIG_DIR"
      log "Removed configuration: $CONFIG_DIR"
    fi
  fi

  # Remove PATH addition from shell rc (safer — only remove the specific line)
  for rcfile in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    if [ -f "$rcfile" ] && grep -q "Added by VPLink 3.0 installer" "$rcfile" 2>/dev/null; then
      # Create temp file with only non-VPLink lines
      local tmp_rc="${rcfile}.vplink_tmp"
      awk '/Added by VPLink 3.0 installer/{skip=1; next} /export PATH=.*\.local\.bin/{if(skip) {skip=0; next} else {next}} {skip=0; print}' "$rcfile" > "$tmp_rc" 2>/dev/null
      if [ -s "$tmp_rc" ]; then
        mv "$tmp_rc" "$rcfile"
        info "Cleaned PATH entry from $(basename "$rcfile")"
      else
        rm -f "$tmp_rc"
      fi
    fi
  done

  echo ""
  log "Uninstall complete"
  echo ""
  echo "  To also remove cached data: rm -rf ~/.vplink3.0"
  echo ""
}

# ═══════════════════════════════════════════════════════════════
#  UPDATE
# ═══════════════════════════════════════════════════════════════

self_update() {
  echo ""
  echo "╔══════════════════════════════════════════════╗"
  echo "║        VPLink 3.0 — Update                  ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""

  if [ ! -d "$INSTALL_DIR/.git" ]; then
    fail "Not a git repository — cannot update"
    info "Reinstall: curl -fsSL $RAW_BASE/install.sh | bash"
    return 1
  fi

  cd "$INSTALL_DIR" || { fail "Cannot access $INSTALL_DIR"; return 1; }
  local old_hash
  old_hash=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

  info "Fetching updates..."
  git fetch origin >> "$LOG_FILE" 2>&1 || {
    fail "Network error during fetch — check connection"
    return 1
  }

  local behind
  behind=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  if [ "$behind" -eq 0 ]; then
    log "Already up to date ($old_hash)"
    return 0
  fi

  info "Updating ($behind new commit(s))..."

  # Check for uncommitted changes
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    warn "Uncommitted changes detected — stashing before update"
    git stash --include-untracked 2>/dev/null || true
  fi

  git pull --ff-only origin main >> "$LOG_FILE" 2>&1 || {
    warn "Fast-forward failed, trying reset to origin/main..."
    git reset --hard origin/main >> "$LOG_FILE" 2>&1 || {
      fail "Update failed — manual intervention needed"
      info "Try: cd $INSTALL_DIR && git fetch origin && git reset --hard origin/main"
      return 1
    }
  }

  # Reinstall npm deps if package.json changed
  if ! git diff --quiet "$old_hash" HEAD -- package.json 2>/dev/null; then
    info "package.json changed — reinstalling npm dependencies..."
    npm install --no-audit --no-fund >> "$LOG_FILE" 2>&1 || {
      warn "npm install failed after update — run: cd $INSTALL_DIR && npm install"
    }
  fi

  # Reinstall Playwright if needed
  if ! is_termux; then
    npx playwright install chromium 2>/dev/null || {
      warn "Playwright update failed — will retry on first run"
    }
  fi

  local new_hash
  new_hash=$(git rev-parse HEAD 2>/dev/null)
  log "Updated: ${old_hash:0:8} → ${new_hash:0:8}"
  echo ""
  info "Run vplink3.0 to start"
}

# ═══════════════════════════════════════════════════════════════
#  MAIN INSTALL
# ═══════════════════════════════════════════════════════════════

main_install() {
  TOTAL_STEPS=8

  echo ""
  echo "╔══════════════════════════════════════════════╗"
  echo "║     VPLink 3.0 — One-Command Installer      ║"
  echo "║     Version $INSTALL_VERSION                   ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""

  # Step 1: Environment detection
  step 1 "Detecting environment"
  detect_distro
  detect_arch
  debug "Distro: $DISTRO, Family: $DISTRO_FAMILY, Arch: $ARCH"
  log "Detected: $DISTRO ($DISTRO_FAMILY) on $ARCH"

  # Environment summary
  echo "  Environment: $(detect_os) / $DISTRO / $ARCH / libc:$(detect_libc)"
  local mode_info
  mode_info="$(is_root && echo 'Root' || echo 'Non-root')"
  mode_info="$mode_info / $(is_docker && echo 'Container' || echo 'Bare-metal')"
  is_wsl && mode_info="$mode_info / WSL"
  is_ci && mode_info="$mode_info / CI"
  echo "  $mode_info"
  echo "  Log: $LOG_FILE"
  echo ""

  load_state

  # Step 2: System dependencies
  step 2 "Installing system dependencies"
  install_system_deps

  # Step 3: Node.js
  step 3 "Setting up Node.js (>= $MIN_NODE_MAJOR)"
  install_node

  # Step 4: Project setup
  step 4 "Setting up project"
  setup_project

  # Step 5: npm dependencies
  step 5 "Installing npm packages"
  install_npm_deps

  # Step 6: Playwright browser
  step 6 "Installing Playwright Chromium"
  install_playwright

  # Step 7: Global command
  step 7 "Creating global command"
  create_global_command

  # Step 8: Credential setup
  step 8 "Configuring credentials"
  setup_credentials

  # Save final state
  mark_done
  echo ""

  # Verify
  echo "╔══════════════════════════════════════════════╗"
  echo "║           Installation Summary               ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""
  verify_installation
  local verify_errors=$?
  echo ""

  # Success
  if [ "$verify_errors" -gt 0 ]; then
    echo "╔══════════════════════════════════════════════╗"
    echo "║  Installation complete with warnings         ║"
    echo "║  ($verify_errors issue(s) detected — see above)    ║"
    echo "║                                              ║"
    echo "║  Run: vplink3.0                              ║"
    echo "║                                              ║"
    echo "║  Fix issues: bash install.sh                 ║"
    echo "║  Log: $LOG_FILE"
    echo "╚══════════════════════════════════════════════╝"
  else
    echo "╔══════════════════════════════════════════════╗"
    echo "║  Installation complete!                      ║"
    echo "║                                              ║"
    echo "║  Run: vplink3.0                              ║"
    echo "║                                              ║"
    echo "║  Commands:                                   ║"
    echo "║    vplink3.0              — Run automation   ║"
    echo "║    vplink3.0 update       — Update project   ║"
    echo "║    vplink3.0 uninstall    — Remove project   ║"
    echo "║    vplink-desktop         — Virtual desktop  ║"
    echo "║                                              ║"
    echo "║  Config: ~/.vplink3.0/config.json            ║"
    echo "║  Log:    $LOG_FILE"
    echo "╚══════════════════════════════════════════════╝"
  fi
  echo ""
  echo "  ${BOLD}Need VNC?${NC} Run: vplink-desktop password --set"
  echo ""
}

# ═══════════════════════════════════════════════════════════════
#  MAIN DISPATCH
# ═══════════════════════════════════════════════════════════════

# Only run dispatch when executed directly (not when sourced for tests)
if [ "${BASH_SOURCE[0]}" = "$0" ] || [ -z "${BASH_SOURCE[0]}" ]; then

case "${1:-install}" in
  install)
    main_install
    ;;
  uninstall)
    uninstall "${2:-false}"
    exit 0
    ;;
  update)
    self_update
    ;;
  --help|-h)
    echo "VPLink 3.0 Installer v$INSTALL_VERSION"
    echo ""
    echo "Usage:"
    echo "  curl -fsSL $RAW_BASE/install.sh | bash"
    echo "  curl -fsSL $RAW_BASE/install.sh | bash -s -- uninstall"
    echo "  curl -fsSL $RAW_BASE/install.sh | bash -s -- update"
    echo "  bash install.sh"
    echo "  bash install.sh uninstall [--all]"
    echo "  bash install.sh update"
    echo ""
    echo "Environment variables:"
    echo "  VPLINK_DIR=path        Custom install directory"
    echo "  VPLINK_NONINTERACTIVE=1 Skip prompts"
    echo "  VPLINK_DEBUG=1         Verbose debug output"
    ;;
  *)
    echo "Usage: bash install.sh {install|uninstall|update|--help}"
    exit 1
    ;;
  esac

fi

