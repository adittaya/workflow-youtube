#!/usr/bin/env bash
# installer/platforms/linux.sh — Linux-specific installation logic
# Handles debian, fedora, arch, suse, and alpine distro families.
# All functions are idempotent (safe to re-run).
# Depends on: installer/core/packages.sh (pkg_install, pkg_update, pkg_is_installed, etc.)

LINUX_MIN_NODE_MAJOR="${LINUX_MIN_NODE_MAJOR:-18}"

# ───────────────────────────────────────────────────────────────
#  Prerequisites — base packages for build + runtime
# ───────────────────────────────────────────────────────────────

linux_install_prerequisites() {
  set -euo pipefail
  local family="${1:-${DISTRO_FAMILY:-unknown}}"

  _linux_ensure_pkg_update "$family"

  case "$family" in
    debian)
      _linux_debian_prereqs
      ;;
    fedora)
      _linux_fedora_prereqs
      ;;
    arch)
      _linux_arch_prereqs
      ;;
    suse)
      _linux_suse_prereqs
      ;;
    alpine)
      _linux_alpine_prereqs
      ;;
    *)
      _linux_fallback_prereqs
      ;;
  esac
}

_linux_ensure_pkg_update() {
  local family="$1"
  if type pkg_update &>/dev/null; then
    pkg_update || true
  else
    case "$family" in
      debian) sudo apt-get update -qq 2>/dev/null || true ;;
      fedora) sudo dnf check-update -q 2>/dev/null || true ;;
      arch) sudo pacman -Sy --noconfirm 2>/dev/null || true ;;
      suse)  sudo zypper refresh 2>/dev/null || true ;;
      alpine) sudo apk update -q 2>/dev/null || true ;;
    esac
  fi
}

_linux_debian_prereqs() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  # Update package index (idempotent — cached after first run)
  $SUDO apt-get update -qq 2>/dev/null || true

  # Core packages
  local pkgs=(
    curl wget git ca-certificates gnupg lsb-release
    build-essential make gcc g++ python3 python3-pip
    jq unzip xz-utils
  )

  # Chromium runtime libraries
  local chromium_runtime_pkgs=(
    libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64
    libcups2t64 libdrm2 libdbus-1-3 libxkbcommon0
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2
    libgbm1 libpango-1.0-0 libcairo2 libasound2t64
  )

  # Chromium browser (name varies by distro version)
  local chromium_browser_pkg="chromium-browser"

  # Virtual display
  local display_pkgs=(xvfb x11vnc)

  # Install in batches for better error handling
  $SUDO apt-get install -y -qq "${pkgs[@]}" 2>/dev/null || true

  # Install Chromium browser (try chromium-browser first, then chromium)
  $SUDO apt-get install -y -qq "$chromium_browser_pkg" 2>/dev/null \
    || $SUDO apt-get install -y -qq chromium 2>/dev/null || true

  # Install Chromium runtime libraries
  $SUDO apt-get install -y -qq "${chromium_runtime_pkgs[@]}" 2>/dev/null || {
    # Fallback without t64 suffix (older Ubuntu)
    $SUDO apt-get install -y -qq \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
      libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
      libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
      libcairo2 libasound2 ca-certificates 2>/dev/null || true
  }

  $SUDO apt-get install -y -qq "${display_pkgs[@]}" 2>/dev/null || true

  log "Debian prerequisites installed"
}

_linux_fedora_prereqs() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  local pkgs=(
    curl wget git ca-certificates
    make gcc gcc-c++ python3 python3-pip
    jq unzip xz
  )

  local chromium_pkgs=(
    chromium nss nspr atk at-spi2-atk cups-libs
    libdrm dbus-libs libxkbcommon libXcomposite
    libXdamage libXfixes libXrandr libgbm
    pango cairo alsa-lib
  )

  local display_pkgs=(
    xorg-x11-server-Xvfb x11vnc
  )

  $SUDO dnf install -y "${pkgs[@]}" 2>/dev/null || true
  $SUDO dnf install -y "${chromium_pkgs[@]}" 2>/dev/null || true
  $SUDO dnf install -y "${display_pkgs[@]}" 2>/dev/null || true

  log "Fedora prerequisites installed"
}

_linux_arch_prereqs() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  local pkgs=(
    curl wget git ca-certificates
    base-devel make gcc python python-pip
    jq unzip xz
    chromium nss nspr atk at-spi2-atk cups libdrm
    dbus libxkbcommon libxcomposite libxdamage
    libxfixes libxrandr libgbm pango cairo alsa-lib
    xorg-server-xvfb x11vnc
  )

  $SUDO pacman -S --noconfirm --needed "${pkgs[@]}" 2>/dev/null || true

  log "Arch prerequisites installed"
}

_linux_suse_prereqs() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  local pkgs=(
    curl wget git ca-certificates
    make gcc gcc-c++ python3 python3-pip
    jq unzip xz
  )

  local chromium_pkgs=(
    chromium nss nspr atk at-spi2-atk cups-libs
    libdrm dbus-1 libxkbcommon0 libxcomposite1
    libxdamage1 libxfixes3 libxrandr2 libgbm1
    pango cairo alsa-lib
  )

  local display_pkgs=(
    xvfb x11vnc
  )

  $SUDO zypper install -y "${pkgs[@]}" 2>/dev/null || true
  $SUDO zypper install -y "${chromium_pkgs[@]}" 2>/dev/null || true
  $SUDO zypper install -y "${display_pkgs[@]}" 2>/dev/null || true

  log "SUSE prerequisites installed"
}

_linux_alpine_prereqs() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  local pkgs=(
    curl wget git ca-certificates
    make gcc g++ python3 py3-pip
    jq unzip xz
    chromium nss nspr atk at-spi2-atk cups-libs
    libdrm dbus libxkbcommon libxcomposite
    libxdamage libxfixes libxrandr libgbm
    pango cairo alsa-lib
    xvfb x11vnc
  )

  $SUDO apk add -q "${pkgs[@]}" 2>/dev/null || true

  log "Alpine prerequisites installed"
}

_linux_fallback_prereqs() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  # Try every known package manager
  for pm in apt-get dnf pacman zypper apk; do
    if command -v "$pm" &>/dev/null; then
      info "Fallback: using $pm for prerequisites"
      case "$pm" in
        apt-get)
          $SUDO apt-get update -qq 2>/dev/null || true
          $SUDO apt-get install -y -qq \
            curl wget git ca-certificates build-essential jq unzip \
            chromium-browser xvfb x11vnc 2>/dev/null || true
          ;;
        dnf)
          $SUDO dnf install -y \
            curl wget git ca-certificates make gcc gcc-c++ jq unzip \
            chromium xorg-x11-server-Xvfb x11vnc 2>/dev/null || true
          ;;
        pacman)
          $SUDO pacman -S --noconfirm --needed \
            curl wget git ca-certificates base-devel jq unzip \
            chromium xorg-server-xvfb x11vnc 2>/dev/null || true
          ;;
        zypper)
          $SUDO zypper install -y \
            curl wget git ca-certificates make gcc gcc-c++ jq unzip \
            chromium xvfb x11vnc 2>/dev/null || true
          ;;
        apk)
          $SUDO apk add -q \
            curl wget git ca-certificates make gcc g++ jq unzip \
            chromium xvfb x11vnc 2>/dev/null || true
          ;;
      esac
      return 0
    fi
  done

  warn "No recognized package manager found — skipping prerequisite installation"
}

# ───────────────────────────────────────────────────────────────
#  Node.js
# ───────────────────────────────────────────────────────────────

linux_install_node() {
  set -euo pipefail
  local min_major="${1:-$LINUX_MIN_NODE_MAJOR}"

  # Already satisfied?
  if _linux_node_meets_requirement "$min_major"; then
    log "Node.js $(node -v 2>/dev/null) meets requirement (>= $min_major)"
    return 0
  fi

  # Try nvm first (works for non-root users)
  if [ -n "${HOME:-}" ] && [ -d "$HOME/.nvm" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh" 2>/dev/null || true
    if command -v nvm &>/dev/null; then
      info "Installing Node.js via nvm..."
      nvm install "$min_major" 2>/dev/null || nvm install node 2>/dev/null || true
      nvm alias default "$min_major" 2>/dev/null || true
      if _linux_node_meets_requirement "$min_major"; then
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
    if _linux_node_meets_requirement "$min_major"; then
      log "Node.js $(node -v) installed via fnm"
      return 0
    fi
  fi

  # Try n (npm package manager helper)
  if command -v n &>/dev/null; then
    info "Installing Node.js via n..."
    local SUDO=""
    _linux_need_sudo && SUDO="sudo"
    $SUDO n "$min_major" 2>/dev/null || true
    if _linux_node_meets_requirement "$min_major"; then
      log "Node.js $(node -v) installed via n"
      return 0
    fi
  fi

  # Try distro package manager
  if _linux_install_node_package_manager "$min_major"; then
    return 0
  fi

  # Direct binary download (last resort)
  _linux_install_node_binary "$min_major"
}

_linux_node_meets_requirement() {
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

_linux_install_node_package_manager() {
  local min_major="$1"
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"
  local family="${DISTRO_FAMILY:-unknown}"

  case "$family" in
    debian)
      # Try NodeSource
      if ! _linux_node_meets_requirement "$min_major"; then
        info "Adding NodeSource repository..."
        curl -fsSL https://deb.nodesource.com/setup_${min_major}.x 2>/dev/null \
          | $SUDO -E bash - 2>/dev/null || {
          warn "NodeSource setup failed — trying apt"
          $SUDO apt-get install -y -qq nodejs 2>/dev/null || true
        }
        $SUDO apt-get install -y -qq nodejs 2>/dev/null || true
        # Debian may install nodejs without node symlink
        if ! command -v node &>/dev/null && command -v nodejs &>/dev/null; then
          $SUDO ln -sf "$(command -v nodejs)" /usr/local/bin/node 2>/dev/null || true
        fi
      fi
      ;;
    fedora)
      $SUDO dnf module enable -y nodejs:${min_major}/common 2>/dev/null || true
      $SUDO dnf install -y nodejs 2>/dev/null || true
      ;;
    arch)
      $SUDO pacman -S --noconfirm --needed nodejs npm 2>/dev/null || true
      ;;
    suse)
      $SUDO zypper install -y nodejs${min_major} 2>/dev/null \
        || $SUDO zypper install -y nodejs 2>/dev/null || true
      ;;
    alpine)
      $SUDO apk add -q nodejs npm 2>/dev/null || true
      ;;
    *)
      return 1
      ;;
  esac

  _linux_node_meets_requirement "$min_major"
}

_linux_install_node_binary() {
  local min_major="$1"
  local ver="20.19.1"
  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64|amd64) arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    armv7l|armhf) arch="armv7l" ;;
    *) arch="x64" ;;
  esac

  local family="${DISTRO_FAMILY:-unknown}"
  local suffix=""
  [ "$family" = "alpine" ] && suffix="-musl"

  local url="https://nodejs.org/dist/v${ver}/node-v${ver}-linux-${arch}${suffix}.tar.xz"
  local tmp_dir="/tmp/vplink-node-install-$$"
  mkdir -p "$tmp_dir"

  info "Downloading Node.js v${ver} (linux-${arch}${suffix})..."
  if ! curl -fsSL --connect-timeout 30 --max-time 300 \
       -o "$tmp_dir/node.tar.xz" "$url"; then
    warn "Download failed: $url"
    rm -rf "$tmp_dir"
    return 1
  fi

  if [ ! -s "$tmp_dir/node.tar.xz" ]; then
    warn "Downloaded Node.js archive is empty"
    rm -rf "$tmp_dir"
    return 1
  fi

  tar -xf "$tmp_dir/node.tar.xz" -C "$tmp_dir" || {
    warn "Extraction failed — archive may be corrupt"
    rm -rf "$tmp_dir"
    return 1
  }

  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  local extract_dir
  extract_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "node-v*" | head -1)
  if [ -z "$extract_dir" ]; then
    warn "Could not find extracted Node.js directory"
    rm -rf "$tmp_dir"
    return 1
  fi

  # Install to /usr/local (or ~/.local for non-root)
  local install_base="/usr/local"
  if ! _linux_need_sudo; then
    mkdir -p "$HOME/.local/bin"
    install_base="$HOME/.local"
  fi

  $SUDO cp -r "$extract_dir/bin/"* "$install_base/bin/" 2>/dev/null || {
    warn "Failed to copy Node.js binaries"
    rm -rf "$tmp_dir"
    return 1
  }
  $SUDO cp -r "$extract_dir/lib/"* "$install_base/lib/" 2>/dev/null || true

  rm -rf "$tmp_dir"

  if _linux_node_meets_requirement "$min_major"; then
    log "Node.js v${ver} installed to $install_base/bin"
    return 0
  fi

  warn "Node.js binary installed but not found in PATH"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  Chromium
# ───────────────────────────────────────────────────────────────

linux_install_chromium() {
  set -euo pipefail

  # Already available?
  if command -v chromium-browser &>/dev/null \
      || command -v chromium &>/dev/null \
      || command -v google-chrome &>/dev/null \
      || command -v google-chrome-stable &>/dev/null; then
    log "Chromium already installed: $(command -v chromium-browser || command -v chromium || command -v google-chrome || command -v google-chrome-stable)"
    return 0
  fi

  local family="${DISTRO_FAMILY:-unknown}"
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  case "$family" in
    debian)
      $SUDO apt-get install -y -qq chromium-browser 2>/dev/null \
        || $SUDO apt-get install -y -qq chromium 2>/dev/null || {
        warn "chromium-browser/chromium not in repos, adding flatpak or snap..."
        if command -v snap &>/dev/null; then
          $SUDO snap install chromium 2>/dev/null || true
        fi
      }
      ;;
    fedora)
      $SUDO dnf install -y chromium 2>/dev/null || true
      ;;
    arch)
      $SUDO pacman -S --noconfirm --needed chromium 2>/dev/null || true
      ;;
    suse)
      $SUDO zypper install -y chromium 2>/dev/null || true
      ;;
    alpine)
      $SUDO apk add -q chromium 2>/dev/null || true
      ;;
    *)
      _linux_fallback_chromium
      ;;
  esac

  if command -v chromium-browser &>/dev/null \
      || command -v chromium &>/dev/null \
      || command -v google-chrome &>/dev/null; then
    log "Chromium installed successfully"
  else
    warn "Chromium install failed — Playwright may download its own browser"
  fi
}

_linux_fallback_chromium() {
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  for pm in apt-get dnf pacman zypper apk; do
    if command -v "$pm" &>/dev/null; then
      case "$pm" in
        apt-get) $SUDO apt-get install -y -qq chromium-browser chromium 2>/dev/null || true ;;
        dnf)     $SUDO dnf install -y chromium 2>/dev/null || true ;;
        pacman)  $SUDO pacman -S --noconfirm chromium 2>/dev/null || true ;;
        zypper)  $SUDO zypper install -y chromium 2>/dev/null || true ;;
        apk)     $SUDO apk add -q chromium 2>/dev/null || true ;;
      esac
      return 0
    fi
  done
}

# ───────────────────────────────────────────────────────────────
#  Xvfb (virtual framebuffer)
# ───────────────────────────────────────────────────────────────

linux_install_xvfb() {
  set -euo pipefail

  # Already available?
  if command -v Xvfb &>/dev/null || command -v xvfb-run &>/dev/null; then
    log "Xvfb already installed"
    return 0
  fi

  local family="${DISTRO_FAMILY:-unknown}"
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  case "$family" in
    debian)
      $SUDO apt-get install -y -qq xvfb 2>/dev/null || true
      ;;
    fedora)
      $SUDO dnf install -y xorg-x11-server-Xvfb 2>/dev/null || true
      ;;
    arch)
      $SUDO pacman -S --noconfirm --needed xorg-server-xvfb 2>/dev/null || true
      ;;
    suse)
      $SUDO zypper install -y xvfb 2>/dev/null || true
      ;;
    alpine)
      $SUDO apk add -q xvfb 2>/dev/null || true
      ;;
    *)
      for pm in apt-get dnf pacman zypper apk; do
        if command -v "$pm" &>/dev/null; then
          case "$pm" in
            apt-get) $SUDO apt-get install -y -qq xvfb 2>/dev/null || true ;;
            dnf)     $SUDO dnf install -y xorg-x11-server-Xvfb 2>/dev/null || true ;;
            pacman)  $SUDO pacman -S --noconfirm xorg-server-xvfb 2>/dev/null || true ;;
            zypper)  $SUDO zypper install -y xvfb 2>/dev/null || true ;;
            apk)     $SUDO apk add -q xvfb 2>/dev/null || true ;;
          esac
          break
        fi
      done
      ;;
  esac

  if command -v Xvfb &>/dev/null || command -v xvfb-run &>/dev/null; then
    log "Xvfb installed"
  else
    warn "Xvfb installation failed"
  fi
}

# ───────────────────────────────────────────────────────────────
#  x11vnc
# ───────────────────────────────────────────────────────────────

linux_install_x11vnc() {
  set -euo pipefail

  if command -v x11vnc &>/dev/null; then
    log "x11vnc already installed"
    return 0
  fi

  local family="${DISTRO_FAMILY:-unknown}"
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  case "$family" in
    debian)
      $SUDO apt-get install -y -qq x11vnc 2>/dev/null || true
      ;;
    fedora)
      $SUDO dnf install -y x11vnc 2>/dev/null || true
      ;;
    arch)
      $SUDO pacman -S --noconfirm --needed x11vnc 2>/dev/null || true
      ;;
    suse)
      $SUDO zypper install -y x11vnc 2>/dev/null || true
      ;;
    alpine)
      $SUDO apk add -q x11vnc 2>/dev/null || true
      ;;
    *)
      for pm in apt-get dnf pacman zypper apk; do
        if command -v "$pm" &>/dev/null; then
          case "$pm" in
            apt-get) $SUDO apt-get install -y -qq x11vnc 2>/dev/null || true ;;
            dnf)     $SUDO dnf install -y x11vnc 2>/dev/null || true ;;
            pacman)  $SUDO pacman -S --noconfirm x11vnc 2>/dev/null || true ;;
            zypper)  $SUDO zypper install -y x11vnc 2>/dev/null || true ;;
            apk)     $SUDO apk add -q x11vnc 2>/dev/null || true ;;
          esac
          break
        fi
      done
      ;;
  esac

  if command -v x11vnc &>/dev/null; then
    log "x11vnc installed"
  else
    warn "x11vnc installation failed"
  fi
}

# ───────────────────────────────────────────────────────────────
#  Virtual Desktop Setup
# ───────────────────────────────────────────────────────────────

linux_setup_desktop() {
  set -euo pipefail

  local display="${VPLINK_DISPLAY:-:99}"
  local resolution="${VPLINK_RESOLUTION:-1920x1080x24}"

  # Check if Xvfb is available
  if ! command -v Xvfb &>/dev/null; then
    warn "Xvfb not installed — cannot setup virtual desktop"
    return 1
  fi

  # Kill any existing Xvfb on this display
  _linux_kill_display "$display"

  # Start Xvfb
  info "Starting Xvfb on $display (${resolution})..."
  Xvfb "$display" -screen 0 "$resolution" -ac +extension GLX +render -noreset \
    &>/dev/null &
  local xvfb_pid=$!

  # Wait for X server to be ready
  local retries=0
  while [ $retries -lt 20 ]; do
    if xdpyinfo -display "$display" &>/dev/null 2>&1; then
      break
    fi
    sleep 0.5
    retries=$((retries + 1))
  done

  if ! xdpyinfo -display "$display" &>/dev/null 2>&1; then
    warn "Xvfb may not have started correctly on $display"
    # Still set DISPLAY so downstream tools can try
  fi

  export DISPLAY="$display"

  # Save PID for cleanup
  local state_dir="${HOME}/.vplink3.0"
  mkdir -p "$state_dir"
  echo "$xvfb_pid" > "$state_dir/xvfb.pid" 2>/dev/null || true
  echo "$display" > "$state_dir/xvfb.display" 2>/dev/null || true

  log "Virtual desktop started on $display (PID: $xvfb_pid)"
}

linux_stop_desktop() {
  local display="${1:-${VPLINK_DISPLAY:-:99}}"
  _linux_kill_display "$display"

  local state_dir="${HOME}/.vplink3.0"
  if [ -f "$state_dir/xvfb.pid" ]; then
    local pid
    pid=$(cat "$state_dir/xvfb.pid" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$state_dir/xvfb.pid"
  fi
  log "Virtual desktop stopped"
}

_linux_kill_display() {
  local display="$1"
  # Kill any Xvfb process using this display
  local pids
  pids=$(pgrep -f "Xvfb.*${display}" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs -r kill 2>/dev/null || true
    sleep 0.5
    echo "$pids" | xargs -r kill -9 2>/dev/null || true
  fi
}

# ───────────────────────────────────────────────────────────────
#  Cleanup
# ───────────────────────────────────────────────────────────────

linux_cleanup() {
  set -euo pipefail
  local family="${DISTRO_FAMILY:-unknown}"
  local SUDO=""
  _linux_need_sudo && SUDO="sudo"

  info "Cleaning up temporary files..."

  # Remove downloaded archives
  rm -rf /tmp/vplink-node-install-* 2>/dev/null || true
  rm -rf /tmp/node-install-* 2>/dev/null || true

  # Clean package manager caches
  case "$family" in
    debian)
      $SUDO apt-get autoremove -y -qq 2>/dev/null || true
      $SUDO apt-get clean 2>/dev/null || true
      rm -rf /var/lib/apt/lists/* 2>/dev/null || true
      ;;
    fedora)
      $SUDO dnf clean all 2>/dev/null || true
      $SUDO dnf autoremove -y 2>/dev/null || true
      ;;
    arch)
      $SUDO pacman -Scc --noconfirm 2>/dev/null || true
      ;;
    suse)
      $SUDO zypper clean --all 2>/dev/null || true
      ;;
    alpine)
      $SUDO apk cache -q purge 2>/dev/null || true
      rm -rf /var/cache/apk/* 2>/dev/null || true
      ;;
    *)
      for pm in apt-get dnf pacman zypper apk; do
        if command -v "$pm" &>/dev/null; then
          case "$pm" in
            apt-get) $SUDO apt-get clean 2>/dev/null || true ;;
            dnf)     $SUDO dnf clean all 2>/dev/null || true ;;
            pacman)  $SUDO pacman -Scc --noconfirm 2>/dev/null || true ;;
            zypper)  $SUDO zypper clean --all 2>/dev/null || true ;;
            apk)     $SUDO apk cache -q purge 2>/dev/null || true ;;
          esac
          break
        fi
      done
      ;;
  esac

  # Remove general temp files
  rm -rf /tmp/vplink-* 2>/dev/null || true

  log "Cleanup complete"
}

# ───────────────────────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────────────────────

_linux_need_sudo() {
  [ "$(id -u)" -ne 0 ]
}

# Source logging helpers if available
if type log &>/dev/null; then
  :  # already sourced
elif [ -f "${BASH_SOURCE[0]%/*}/../logging/logger.sh" ]; then
  # shellcheck disable=SC1091
  source "${BASH_SOURCE[0]%/*}/../logging/logger.sh"
else
  # Minimal fallbacks
  log()   { echo "[OK] $*"; }
  warn()  { echo "[WARN] $*"; }
  fail()  { echo "[FAIL] $*" >&2; }
  info()  { echo "[INFO] $*"; }
fi
