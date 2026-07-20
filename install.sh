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
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=8
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

log()   { echo -e "  ${GREEN}$(printf '\xe2\x9c\x93')${NC} $1"; echo "[$(date +%T)] OK  $1" >> "$LOG_FILE"; }
warn()  { echo -e "  ${YELLOW}$(printf '\xe2\x9a\xa0')${NC} $1"; echo "[$(date +%T)] WARN $1" >> "$LOG_FILE"; }
fail()  { echo -e "  ${RED}$(printf '\xe2\x9c\x97')${NC} $1"; echo "[$(date +%T)] FAIL $1" >> "$LOG_FILE"; }
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
  case "$(uname -s)" in
    Darwin) OS="macos" ;;
    Linux)  OS="linux" ;;
    *)      OS="unknown" ;;
  esac
  echo "$OS"
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
STATE_PYTHON=""
STATE_PIP_DEPS=""
STATE_CHROMEDRIVER=""
STATE_CMD=""
STATE_CREDENTIALS=""

load_state() {
  [ -f "$STATE_FILE" ] || return 0
  local s
  s=$(cat "$STATE_FILE")
  # Portable extraction — no grep -oP (not available on macOS)
  STATE_SYS_DEPS=$(echo "$s" | sed -n 's/.*"sys_deps"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_PYTHON=$(echo "$s" | sed -n 's/.*"python"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_PIP_DEPS=$(echo "$s" | sed -n 's/.*"pip_deps"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_CHROMEDRIVER=$(echo "$s" | sed -n 's/.*"chromedriver"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_CMD=$(echo "$s" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
  STATE_CREDENTIALS=$(echo "$s" | sed -n 's/.*"credentials"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
}

save_state() {
  mkdir -p "$(dirname "$STATE_FILE")"
  cat > "$STATE_FILE" <<EOF
{
  "sys_deps": "${STATE_SYS_DEPS:-done}",
  "python": "${STATE_PYTHON:-done}",
  "pip_deps": "${STATE_PIP_DEPS:-done}",
  "chromedriver": "${STATE_CHROMEDRIVER:-done}",
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
    pkg install -y curl git python chromium x11-repo || true
  elif [ "$DISTRO_FAMILY" = "debian" ]; then
    $SUDO apt-get update -qq 2>/dev/null || warn "apt-get update failed — using cache"
    $SUDO apt-get install -y -qq curl git xvfb x11vnc jq chromium-browser \
      chromium-chromedriver \
      libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
      libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
      libasound2t64 libxshmfence1 ca-certificates || \
    $SUDO apt-get install -y -qq curl git xvfb x11vnc jq chromium-browser \
      chromium-chromedriver \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
      libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
      libasound2 libxshmfence1 ca-certificates || \
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
#  PYTHON MANAGEMENT
# ═══════════════════════════════════════════════════════════════

install_python() {
  [ "$STATE_PYTHON" = "done" ] && { log "Python already installed"; return 0; }

  if has_cmd python3; then
    local py_ver
    py_ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    local py_major py_minor
    py_major=$(echo "$py_ver" | cut -d. -f1)
    py_minor=$(echo "$py_ver" | cut -d. -f2)
    if [ "$py_major" -ge "$MIN_PYTHON_MAJOR" ] 2>/dev/null && [ "$py_minor" -ge "$MIN_PYTHON_MINOR" ] 2>/dev/null; then
      log "Python $py_ver meets requirement (>= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
      STATE_PYTHON="done"
      return 0
    else
      warn "Python $py_ver is too old (need >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
    fi
  fi

  if is_termux; then
    pkg install -y python
  elif is_root; then
    install_python_pkg
  else
    install_python_pkg
  fi

  if has_cmd python3; then
    log "Python $(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') installed"
    STATE_PYTHON="done"
  else
    fail "Python installation failed"
    return 1
  fi
}

install_python_pkg() {
  case "$DISTRO_FAMILY" in
    debian) $SUDO apt-get install -y -qq python3 python3-pip python3-venv >> "$LOG_FILE" 2>&1 || warn "Some Python packages failed — see log" ;;
    fedora) $SUDO dnf install -y python3 python3-pip >> "$LOG_FILE" 2>&1 || warn "Some Python packages failed — see log" ;;
    arch) $SUDO pacman -S --noconfirm python python-pip >> "$LOG_FILE" 2>&1 || warn "Some Python packages failed — see log" ;;
    suse) $SUDO zypper install -y python3 python3-pip >> "$LOG_FILE" 2>&1 || warn "Some Python packages failed — see log" ;;
    alpine) $SUDO apk add python3 py3-pip >> "$LOG_FILE" 2>&1 || warn "Some Python packages failed — see log" ;;
    *) warn "Unknown distro — attempting python3 install..." ; $SUDO apt-get install -y python3 python3-pip >> "$LOG_FILE" 2>&1 || true ;;
  esac
}

install_pip_deps() {
  [ "$STATE_PIP_DEPS" = "done" ] && { log "Python dependencies already installed"; return 0; }

  cd "$INSTALL_DIR" 2>/dev/null || { warn "Project directory missing, skipping pip install"; return 0; }
  info "Installing Python dependencies..."

  # ── 1. Ensure pip itself works ───────────────────────────
  if ! python3 -m pip --version >> "$LOG_FILE" 2>&1; then
    info "pip not found — installing..."
    if command -v apt-get &>/dev/null; then
      $SUDO apt-get install -y -qq python3-pip python3-venv >> "$LOG_FILE" 2>&1 || true
    fi
    if ! python3 -m pip --version >> "$LOG_FILE" 2>&1; then
      python3 -m ensurepip --upgrade >> "$LOG_FILE" 2>&1 || true
    fi
    if ! python3 -m pip --version >> "$LOG_FILE" 2>&1; then
      warn "pip not available — install manually: sudo apt-get install python3-pip"
      STATE_PIP_DEPS="failed"
      return 0
    fi
  fi

  # ── 2. Try apt-based packages first (more reliable) ──────
  if [ "$DISTRO_FAMILY" = "debian" ] && command -v apt-get &>/dev/null; then
    $SUDO apt-get install -y -qq python3-selenium python3-requests 2>/dev/null || true
  fi

  # ── 3. Upgrade pip (compatibility with new Python) ──────
  python3 -m pip install --upgrade pip >> "$LOG_FILE" 2>&1 || true

  # ── 4. Try pip install with multiple fallbacks ──────────
  local pip_ok=false
  for pip_cmd in \
    "python3 -m pip install --user -r requirements.txt" \
    "python3 -m pip install --break-system-packages -r requirements.txt" \
    "PIP_REQUIRE_VIRTUALENV=0 python3 -m pip install --user -r requirements.txt" \
    "python3 -m pip install -r requirements.txt" \
    "python3 -m pip install --no-build-isolation --user -r requirements.txt" \
    "python3 -m pip install selenium webdriver-manager requests urllib3"; do
    debug "Trying: $pip_cmd"
    if eval "$pip_cmd" >> "$LOG_FILE" 2>&1; then
      pip_ok=true
      break
    fi
  done

  # ── 5. Last resort: venv ────────────────────────────────
  if ! $pip_ok; then
    info "pip install failed — trying virtual environment..."
    python3 -m venv "$INSTALL_DIR/.venv" >> "$LOG_FILE" 2>&1 && {
      source "$INSTALL_DIR/.venv/bin/activate" 2>/dev/null || true
      if "$INSTALL_DIR/.venv/bin/pip" install -r requirements.txt >> "$LOG_FILE" 2>&1; then
        pip_ok=true
        info "Installed in venv at $INSTALL_DIR/.venv"
        info "Activate: source $INSTALL_DIR/.venv/bin/activate"
      fi
    }
  fi

  if $pip_ok; then
    STATE_PIP_DEPS="done"
    log "Python dependencies installed"
  else
    warn "pip install failed — last 20 lines of log:"
    tail -20 "$LOG_FILE" | sed 's/^/    /'
    STATE_PIP_DEPS="failed"
  fi
}

install_chromedriver() {
  [ "$STATE_CHROMEDRIVER" = "done" ] && { log "Chromedriver already available"; return 0; }

  if is_termux; then
    log "Termux: using system Chromium, skipping chromedriver install"
    STATE_CHROMEDRIVER="done"
    return 0
  fi

  # Install chromedriver package if available
  if [ "$DISTRO_FAMILY" = "debian" ] && command -v apt-get &>/dev/null; then
    info "Installing chromium-chromedriver..."
    $SUDO apt-get install -y -qq chromium-chromedriver >> "$LOG_FILE" 2>&1 || true
    # On newer Ubuntu, chromedriver may be at /snap/bin/chromium.chromedriver
    if [ -x /snap/bin/chromium.chromedriver ] && [ ! -f /usr/bin/chromedriver ]; then
      $SUDO ln -sf /snap/bin/chromium.chromedriver /usr/bin/chromedriver 2>/dev/null || true
    fi
  fi

  # Verify chromedriver binary exists
  if [ -x /usr/bin/chromedriver ] || [ -x /snap/bin/chromium.chromedriver ]; then
    STATE_CHROMEDRIVER="done"
    log "Chromedriver installed"
  elif command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null || command -v google-chrome &>/dev/null; then
    warn "Chromium found but chromedriver not installed — webdriver-manager will attempt to download on first run"
    STATE_CHROMEDRIVER="pending"
  else
    warn "Chromium not found and chromedriver not installed — webdriver-manager will attempt to download on first run"
    STATE_CHROMEDRIVER="pending"
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
      local stashed=false
      if ! git diff --quiet 2>/dev/null; then
        warn "Local changes detected — stashing..."
        git stash --include-untracked 2>/dev/null || true
        stashed=true
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
      # Restore stashed changes if possible
      if [ "$stashed" = "true" ]; then
        git stash pop 2>/dev/null || warn "Could not restore stashed changes — check: git stash list"
      fi
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
        export PATH="$HOME/.local/bin:$PATH"
        # Primary: interactive shell rc (bashrc for bash, zshrc for zsh)
        local rcfile="$HOME/.bashrc"
        if [ -f "$HOME/.bashrc" ]; then
          rcfile="$HOME/.bashrc"
        elif [ -f "$HOME/.zshrc" ]; then
          rcfile="$HOME/.zshrc"
        fi
        echo "" >> "$rcfile"
        echo "# Added by VPLink 3.0 installer" >> "$rcfile"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rcfile"
        # Secondary: profile (login shells)
        if [ -f "$HOME/.profile" ] && [ "$rcfile" != "$HOME/.profile" ]; then
          if ! grep -q "Added by VPLink 3.0 installer" "$HOME/.profile" 2>/dev/null; then
            echo "" >> "$HOME/.profile"
            echo "# Added by VPLink 3.0 installer" >> "$HOME/.profile"
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
          fi
        fi
        warn "Added ~/.local/bin to PATH for this session and future shells"
      fi
  fi

  STATE_CMD="done"
  log "Global command $SCRIPT_NAME created"
}

# ═══════════════════════════════════════════════════════════════
#  CREDENTIAL SETUP (first-time only, permanently saved)
# ═══════════════════════════════════════════════════════════════

# Merge new fields into existing config.json (preserves views, mobile_profile, etc.)
_write_merged_config() {
  local proxy_enabled="${1:-false}"
  local tmp="${CREDENTIAL_FILE}.tmp.$$"
  if [ -f "$CREDENTIAL_FILE" ] && has_cmd jq; then
    jq --arg url "$SB_URL" --arg key "$SB_KEY" --arg secret "$SB_SECRET" \
       --argjson proxy "$proxy_enabled" \
       '. + {supabase_url: $url, supabase_key: $key, supabase_secret: $secret, proxy_enabled: $proxy}' \
       "$CREDENTIAL_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$CREDENTIAL_FILE"
  elif [ -f "$CREDENTIAL_FILE" ]; then
    # No jq — use python to merge if available
    python3 -c "
import json
try:
  p = '$CREDENTIAL_FILE'
  cfg = {}
  try:
    with open(p) as f: cfg = json.load(f)
  except: pass
  cfg['supabase_url'] = '$SB_URL'
  cfg['supabase_key'] = '$SB_KEY'
  cfg['supabase_secret'] = '$SB_SECRET'
  cfg['proxy_enabled'] = $proxy_enabled
  with open(p, 'w') as f: json.dump(cfg, f, indent=2)
except:
  import sys; sys.exit(1)
" 2>/dev/null || {
      # Last resort: write fresh config
      cat > "$CREDENTIAL_FILE" <<EOCFG
{
  "supabase_url": "${SB_URL}",
  "supabase_key": "${SB_KEY}",
  "supabase_secret": "${SB_SECRET}",
  "proxy_enabled": ${proxy_enabled},
  "proxy_tier": "premium",
  "youtube_traffic": false,
  "mobile_profile": false,
  "random_urls": [],
  "vnc_port": 5900,
  "views": 1
}
EOCFG
    }
  else
    # No existing config — write fresh
    cat > "$CREDENTIAL_FILE" <<EOCFG
{
  "supabase_url": "${SB_URL}",
  "supabase_key": "${SB_KEY}",
  "supabase_secret": "${SB_SECRET}",
  "proxy_enabled": ${proxy_enabled},
  "proxy_tier": "premium",
  "youtube_traffic": false,
  "mobile_profile": false,
  "random_urls": [],
  "vnc_port": 5900,
  "views": 1
}
EOCFG
  fi
  rm -f "${CREDENTIAL_FILE}.tmp.$$"
}

setup_credentials() {
  # Already done from install state: verify config actually exists with credentials
  if [ "$STATE_CREDENTIALS" = "done" ]; then
    if [ -f "$CREDENTIAL_FILE" ] && grep -q '"supabase_key"' "$CREDENTIAL_FILE" 2>/dev/null; then
      # Non-interactive or piped: skip silently
      if [ -n "${VPLINK_NONINTERACTIVE:-}" ] || [ -n "${CI:-}" ] || [ ! -t 0 ]; then
        log "Credentials already configured"
        return 0
      fi
      echo ""
      read -r -p "  Credentials already configured. Reconfigure? [y/N] " RECONFIG
      case "$RECONFIG" in
        [yY]|[yY][eE][sS])
          # Fall through to interactive setup
          ;;
        *)
          log "Keeping existing credentials"
          return 0
          ;;
      esac
    else
      warn "State says credentials configured but config file is missing/broken — re-running..."
    fi
  fi

  # Non-interactive mode: skip with warning
  if [ -n "${VPLINK_NONINTERACTIVE:-}" ] || [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    # But check for env-var credentials first
    if [ -n "${SUPABASE_KEY:-}" ] && [ -n "${SUPABASE_SECRET:-}" ]; then
      SB_URL="${SUPABASE_URL:-https://bytemjjijgwwcrxlgutf.supabase.co}"
      SB_KEY="$SUPABASE_KEY"
      SB_SECRET="$SUPABASE_SECRET"
      mkdir -p "$CONFIG_DIR"
      _write_merged_config "true"
      chmod 600 "$CREDENTIAL_FILE"
      STATE_CREDENTIALS="done"
      log "Credentials loaded from environment variables"
      return 0
    fi
    warn "Non-interactive mode — skipping credential setup. Configure later: vplink3.0 proxy --setup"
    STATE_CREDENTIALS="skipped"
    return 0
  fi

  # Check if stdin is a terminal (interactive)
  if [ ! -t 0 ]; then
    # But check for env-var credentials first
    if [ -n "${SUPABASE_KEY:-}" ] && [ -n "${SUPABASE_SECRET:-}" ]; then
      SB_URL="${SUPABASE_URL:-https://bytemjjijgwwcrxlgutf.supabase.co}"
      SB_KEY="$SUPABASE_KEY"
      SB_SECRET="$SUPABASE_SECRET"
      mkdir -p "$CONFIG_DIR"
      _write_merged_config "true"
      chmod 600 "$CREDENTIAL_FILE"
      STATE_CREDENTIALS="done"
      log "Credentials loaded from environment variables"
      return 0
    fi
    warn "No interactive terminal — skipping credential setup. Configure later: vplink3.0 proxy --setup"
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

  # Save credentials (merge with existing config — don't overwrite user settings)
  mkdir -p "$CONFIG_DIR"
  if [ -n "$SB_KEY" ]; then
    # Use config.py save() which merges with existing config
    if [ -f "$INSTALL_DIR/config.py" ]; then
      python3 -c "
import sys; sys.path.insert(0, '$INSTALL_DIR')
from config import save
save({
  'supabase_url': '$(echo "$SB_URL" | sed "s/'/\\\\'/g")',
  'supabase_key': '$(echo "$SB_KEY" | sed "s/'/\\\\'/g")',
  'supabase_secret': '$(echo "$SB_SECRET" | sed "s/'/\\\\'/g")',
  'proxy_enabled': True,
  'proxy_tier': 'premium',
})
" 2>/dev/null || {
        # Fallback: write JSON directly but preserve existing fields
        _write_merged_config "true"
      }
    else
      _write_merged_config "true"
    fi
    chmod 600 "$CREDENTIAL_FILE"
    STATE_CREDENTIALS="done"
    log "Credentials saved to $CREDENTIAL_FILE"
  else
    _write_merged_config "false"
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

  # 2. Python
  if has_cmd python3; then
    local py_ver py_major py_minor
    py_ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    py_major=$(echo "$py_ver" | cut -d. -f1)
    py_minor=$(echo "$py_ver" | cut -d. -f2)
    if [ "$py_major" -ge "$MIN_PYTHON_MAJOR" ] 2>/dev/null && [ "$py_minor" -ge "$MIN_PYTHON_MINOR" ] 2>/dev/null; then
      log "Python $py_ver meets requirement (>= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
    else
      warn "Python $py_ver installed but too old (need >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
      errors=$((errors + 1))
    fi
  else
    fail "Python3 not found"
    errors=$((errors + 1))
  fi

  # 3. Project files
  local required_files=(
    "$INSTALL_DIR/automation.py"
    "$INSTALL_DIR/config.py"
    "$INSTALL_DIR/proxy_rotator.py"
    "$INSTALL_DIR/profile_generator.py"
    "$INSTALL_DIR/vplink3.0.sh"
    "$INSTALL_DIR/vplink-desktop.sh"
    "$INSTALL_DIR/requirements.txt"
  )
  for f in "${required_files[@]}"; do
    if [ -f "$f" ]; then
      log "Found $(basename "$f")"
    else
      fail "Missing: $f"
      errors=$((errors + 1))
    fi
  done

  # 4. Python packages (selenium, webdriver-manager)
  if python3 -c "import selenium" 2>/dev/null; then
    local selenium_ver
    selenium_ver=$(python3 -c "import selenium; print(selenium.__version__)" 2>/dev/null)
    log "selenium $selenium_ver installed"
  else
    warn "selenium not installed — run: pip3 install -r requirements.txt"
    errors=$((errors + 1))
  fi

  # 5. Chromium browser
  local chromium_bin=""
  if is_termux; then
    chromium_bin=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null || echo "")
  else
    chromium_bin=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null || command -v google-chrome 2>/dev/null || echo "")
  fi
  if [ -n "$chromium_bin" ]; then
    log "Chromium found: $chromium_bin"
  else
    warn "Chromium not found — will attempt to install on first run"
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
  running_pids=$(pgrep -f "python3.*automation.py\|vplink3.0" 2>/dev/null | grep -v "^$$\$" || true)
  if [ -n "$running_pids" ]; then
    warn "VPLink processes are running (PIDs: $running_pids)"
    if [ -t 0 ]; then
      read -r -p "Kill running processes before uninstall? (y/N): " kill_procs
      if [[ "$kill_procs" =~ ^[yY] ]]; then
        echo "$running_pids" | xargs -r kill 2>/dev/null || true
        sleep 1
        # Force kill if still alive
        running_pids=$(pgrep -f "python3.*automation.py\|vplink3.0" 2>/dev/null | grep -v "^$$\$" || true)
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

  # Reinstall pip deps if requirements.txt changed
  if ! git diff --quiet "$old_hash" HEAD -- requirements.txt 2>/dev/null; then
    info "requirements.txt changed — reinstalling Python dependencies..."
    python3 -m pip install --user -r requirements.txt >> "$LOG_FILE" 2>&1 || {
      warn "pip install failed after update — run: pip3 install -r requirements.txt"
    }
  fi

  # Verify chromedriver is available
  if ! is_termux; then
    python3 -c "from webdriver_manager.chrome import ChromeDriverManager; ChromeDriverManager().install()" 2>/dev/null || {
      warn "Chromedriver check failed — will retry on first run"
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
  detect_os
  detect_distro
  detect_arch
  debug "Distro: $DISTRO, Family: $DISTRO_FAMILY, Arch: $ARCH"
  log "Detected: $DISTRO ($DISTRO_FAMILY) on $ARCH"

  # Environment summary
  echo "  Environment: $OS / $DISTRO / $ARCH / libc:$(detect_libc)"
  local mode_info
  mode_info="$(is_root && echo 'Root' || echo 'Non-root')"
  mode_info="$mode_info / $(is_docker && echo 'Container' || echo 'Bare-metal')"
  is_wsl && mode_info="$mode_info / WSL"
  is_ci && mode_info="$mode_info / CI"
  echo "  $mode_info"

  # Disk space check (need ~300MB for Chromium + deps)
  local avail_kb
  avail_kb=$(df -k "$HOME" 2>/dev/null | awk 'NR==2{print $4}' || echo 0)
  if [ "$avail_kb" -lt 307200 ] 2>/dev/null; then
    warn "Low disk space: $((avail_kb / 1024))MB available (recommend 300MB+)"
  else
    log "Disk space: $((avail_kb / 1024))MB available"
  fi
  echo "  Log: $LOG_FILE"
  echo ""

  load_state

  # Step 2: System dependencies
  step 2 "Installing system dependencies"
  install_system_deps

  # Step 3: Python
  step 3 "Setting up Python (>= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
  install_python

  # Step 4: Project setup
  step 4 "Setting up project"
  setup_project

  # Step 5: Python dependencies
  step 5 "Installing Python packages"
  install_pip_deps

  # Step 6: Chromium/Chromedriver
  step 6 "Setting up Chromium/Chromedriver"
  install_chromedriver

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
  local verify_errors=0
  verify_installation || verify_errors=$?
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
    echo "║    vplink3.0 proxy --setup— Proxy setup      ║"
    echo "║    vplink3.0 proxy --status— Proxy health    ║"
    echo "║    vplink3.0 config       — Setup credentials║"
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
if [ "${BASH_SOURCE[0]:-}" = "$0" ] || [ -z "${BASH_SOURCE[0]:-}" ]; then

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
    echo "  SUPABASE_URL=url       Supabase URL (skip credential prompt)"
    echo "  SUPABASE_KEY=key       Supabase anon key (skip credential prompt)"
    echo "  SUPABASE_SECRET=secret Supabase secret key (skip credential prompt)"
    ;;
  *)
    echo "Usage: bash install.sh {install|uninstall|update|--help}"
    exit 1
    ;;
  esac

fi

