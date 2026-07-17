#!/usr/bin/env bash
# installer/platforms/windows.sh — Windows-specific installation logic
# Supports Git Bash, MSYS2, Cygwin, and WSL environments.
# Contains bash functions with embedded PowerShell for Windows-native operations.
# All functions are idempotent (safe to re-run).

# ───────────────────────────────────────────────────────────────
#  Environment detection
# ───────────────────────────────────────────────────────────────

windows_detect_environment() {
  WINDOWS_ENV="unknown"

  # WSL
  if grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]; then
    WINDOWS_ENV="wsl"
    return 0
  fi

  # MSYS2
  if [ -n "${MSYSTEM:-}" ]; then
    WINDOWS_ENV="msys2"
    return 0
  fi

  # Git Bash (MINGW)
  case "$(uname -s)" in
    MINGW*|MSYS*)
      if [ -n "${MINGW_PREFIX:-}" ] && echo "$MINGW_PREFIX" | grep -qi msys; then
        WINDOWS_ENV="msys2"
      else
        WINDOWS_ENV="gitbash"
      fi
      return 0
      ;;
  esac

  # Cygwin
  if [ -f /cygdrive/. ] 2>/dev/null || [[ "$(uname -s)" == CYGWIN* ]]; then
    WINDOWS_ENV="cygwin"
    return 0
  fi

  # Native Windows (PowerShell / cmd)
  if [ -n "${OS:-}" ] && [ "$OS" = "Windows_NT" ]; then
    WINDOWS_ENV="native"
    return 0
  fi

  return 1
}

windows_is_wsl() {
  [ "${WINDOWS_ENV:-}" = "wsl" ]
}

windows_is_gitbash() {
  [ "${WINDOWS_ENV:-}" = "gitbash" ]
}

windows_is_msys2() {
  [ "${WINDOWS_ENV:-}" = "msys2" ]
}

windows_is_cygwin() {
  [ "${WINDOWS_ENV:-}" = "cygwin" ]
}

windows_is_native_shell() {
  windows_is_gitbash || windows_is_msys2 || windows_is_cygwin
}

# ───────────────────────────────────────────────────────────────
#  Path conversion helpers
# ───────────────────────────────────────────────────────────────

# Convert Unix path to Windows path
windows_to_winpath() {
  local path="$1"
  if command -v cygpath &>/dev/null; then
    cygpath -w "$path" 2>/dev/null || echo "$path"
  else
    # Manual conversion: /c/foo → C:\foo
    echo "$path" | sed 's|^/\([a-zA-Z]\)/|\U\1:\\|' | sed 's|/|\\|g'
  fi
}

# Convert Windows path to Unix path
windows_to_unixpath() {
  local path="$1"
  if command -v cygpath &>/dev/null; then
    cygpath -u "$path" 2>/dev/null || echo "$path"
  else
    # Manual conversion: C:\foo → /c/foo
    echo "$path" | sed 's|^\([a-zA-Z]\):|\/\L\1|' | sed 's|\\|/|g'
  fi
}

# ───────────────────────────────────────────────────────────────
#  PowerShell execution
# ───────────────────────────────────────────────────────────────

_windows_run_ps() {
  local ps_cmd="$1"

  if windows_is_wsl; then
    # In WSL, use powershell.exe or pwsh.exe from Windows
    if command -v powershell.exe &>/dev/null; then
      powershell.exe -NoProfile -NonInteractive -Command "$ps_cmd" 2>/dev/null
      return $?
    elif command -v pwsh.exe &>/dev/null; then
      pwsh.exe -NoProfile -NonInteractive -Command "$ps_cmd" 2>/dev/null
      return $?
    else
      warn "PowerShell not accessible from WSL"
      return 1
    fi
  fi

  if command -v powershell &>/dev/null; then
    powershell -NoProfile -NonInteractive -Command "$ps_cmd" 2>/dev/null
    return $?
  elif command -v pwsh &>/dev/null; then
    pwsh -NoProfile -NonInteractive -Command "$ps_cmd" 2>/dev/null
    return $?
  elif command -v /c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe &>/dev/null; then
    /c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe \
      -NoProfile -NonInteractive -Command "$ps_cmd" 2>/dev/null
    return $?
  fi

  warn "PowerShell not found — cannot run Windows-native commands"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  Prerequisites (winget / choco / scoop)
# ───────────────────────────────────────────────────────────────

windows_install_prerequisites() {
  set -euo pipefail

  windows_detect_environment || true

  info "Installing Windows prerequisites..."

  # Try winget first (modern Windows package manager)
  if windows_install_prereqs_winget; then
    log "Prerequisites installed via winget"
    return 0
  fi

  # Try Chocolatey
  if windows_install_prereqs_choco; then
    log "Prerequisites installed via Chocolatey"
    return 0
  fi

  # Try scoop
  if windows_install_prereqs_scoop; then
    log "Prerequisites installed via Scoop"
    return 0
  fi

  # If WSL, try apt as fallback for build tools
  if windows_is_wsl; then
    warn "No Windows package manager found — using WSL apt"
    _windows_wsl_prereqs
    return 0
  fi

  warn "No package manager found (winget/choco/scoop)"
  warn "Install manually: https://github.com/microsoft/winget-cli"
  return 1
}

windows_install_prereqs_winget() {
  if ! command -v winget &>/dev/null; then
    return 1
  fi

  local packages=(
    "Git.Git"
    "JanDeDobbeleer.OhMyPosh"
  )

  for pkg in "${packages[@]}"; do
    if winget list --id "$pkg" 2>/dev/null | grep -qi "$pkg"; then
      debug "  $pkg already installed"
    else
      info "  Installing $pkg via winget..."
      winget install --id "$pkg" --accept-source-agreements --accept-package-agreements \
        2>/dev/null || warn "Failed to install $pkg via winget"
    fi
  done

  return 0
}

windows_install_prereqs_choco() {
  if ! command -v choco &>/dev/null; then
    # Try to install Chocolatey first
    if _windows_install_chocolatey; then
      : # installed
    else
      return 1
    fi
  fi

  local packages=(
    git
    nodejs-lts
    jq
    unzip
  )

  for pkg in "${packages[@]}"; do
    if choco list --local-only "$pkg" 2>/dev/null | grep -qi "$pkg"; then
      debug "  $pkg already installed"
    else
      info "  Installing $pkg via Chocolatey..."
      choco install -y "$pkg" 2>/dev/null || warn "Failed to install $pkg via Chocolatey"
    fi
  done

  return 0
}

windows_install_prereqs_scoop() {
  if ! command -v scoop &>/dev/null; then
    return 1
  fi

  local packages=(
    git
    nodejs-lts
    jq
    unzip
  )

  for pkg in "${packages[@]}"; do
    if scoop list "$pkg" 2>/dev/null | grep -qi "$pkg"; then
      debug "  $pkg already installed"
    else
      info "  Installing $pkg via Scoop..."
      scoop install "$pkg" 2>/dev/null || warn "Failed to install $pkg via Scoop"
    fi
  done

  return 0
}

_windows_install_chocolatey() {
  if [ "$(id -u)" -eq 0 ]; then
    warn "Chocolatey should not be installed as root"
    return 1
  fi

  info "Installing Chocolatey..."
  _windows_run_ps "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))" || {
    warn "Chocolatey installation failed"
    return 1
  }

  # Refresh PATH
  export PATH="/c/ProgramData/chocolatey/bin:$PATH"

  if command -v choco &>/dev/null; then
    log "Chocolatey installed"
    return 0
  fi

  return 1
}

_windows_wsl_prereqs() {
  local SUDO=""
  [ "$(id -u)" -ne 0 ] && SUDO="sudo"

  $SUDO apt-get update -qq 2>/dev/null || true
  $SUDO apt-get install -y -qq \
    curl wget git jq unzip build-essential \
    ca-certificates gnupg 2>/dev/null || true
}

# ───────────────────────────────────────────────────────────────
#  Node.js
# ───────────────────────────────────────────────────────────────

windows_install_node() {
  set -euo pipefail
  local min_major="${1:-18}"

  windows_detect_environment || true

  # Check existing installation
  if windows_node_meets_requirement "$min_major"; then
    log "Node.js $(node -v 2>/dev/null) meets requirement (>= $min_major)"
    return 0
  fi

  # In WSL, just use apt / nvm
  if windows_is_wsl; then
    _windows_wsl_install_node "$min_major"
    return $?
  fi

  # Try winget
  if windows_install_node_winget "$min_major"; then
    return 0
  fi

  # Try Chocolatey
  if windows_install_node_choco "$min_major"; then
    return 0
  fi

  # Try Scoop
  if windows_install_node_scoop "$min_major"; then
    return 0
  fi

  # Direct download
  _windows_install_node_binary "$min_major"
}

windows_node_meets_requirement() {
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

windows_install_node_winget() {
  local min_major="$1"
  if ! command -v winget &>/dev/null; then
    return 1
  fi

  info "Installing Node.js v${min_major} via winget..."
  winget install --id OpenJS.NodeJS.LTS \
    --accept-source-agreements --accept-package-agreements \
    2>/dev/null || return 1

  # Refresh PATH
  export PATH="$LOCALAPPDATA/Microsoft/WinGet/Links:$PATH"
  export PATH="/c/Program Files/nodejs:$PATH"
  export PATH="/c/Program Files (x86)/nodejs:$PATH"

  windows_node_meets_requirement "$min_major"
}

windows_install_node_choco() {
  local min_major="$1"
  if ! command -v choco &>/dev/null; then
    return 1
  fi

  info "Installing Node.js v${min_major} via Chocolatey..."
  choco install -y nodejs-lts 2>/dev/null || return 1

  # Refresh PATH
  export PATH="/c/Program Files/nodejs:$PATH"

  windows_node_meets_requirement "$min_major"
}

windows_install_node_scoop() {
  local min_major="$1"
  if ! command -v scoop &>/dev/null; then
    return 1
  fi

  info "Installing Node.js v${min_major} via Scoop..."
  scoop install nodejs-lts 2>/dev/null || return 1

  windows_node_meets_requirement "$min_major"
}

_windows_wsl_install_node() {
  local min_major="$1"

  # Try nvm for WSL
  if [ -n "${HOME:-}" ] && [ -d "$HOME/.nvm" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh" 2>/dev/null || true
    if command -v nvm &>/dev/null; then
      nvm install "$min_major" 2>/dev/null || nvm install node 2>/dev/null || true
      nvm alias default "$min_major" 2>/dev/null || true
      if windows_node_meets_requirement "$min_major"; then
        log "Node.js $(node -v) installed via nvm (WSL)"
        return 0
      fi
    fi
  fi

  # Use apt
  local SUDO=""
  [ "$(id -u)" -ne 0 ] && SUDO="sudo"

  $SUDO apt-get update -qq 2>/dev/null || true

  # NodeSource
  curl -fsSL "https://deb.nodesource.com/setup_${min_major}.x" 2>/dev/null \
    | $SUDO -E bash - 2>/dev/null || true
  $SUDO apt-get install -y -qq nodejs 2>/dev/null || true

  # Debian may install nodejs without node symlink
  if ! command -v node &>/dev/null && command -v nodejs &>/dev/null; then
    $SUDO ln -sf "$(command -v nodejs)" /usr/local/bin/node 2>/dev/null || true
  fi

  windows_node_meets_requirement "$min_major"
}

_windows_install_node_binary() {
  local min_major="$1"
  local ver="20.19.1"
  local arch="x64"
  local url="https://nodejs.org/dist/v${ver}/node-v${ver}-win-${arch}.zip"
  local tmp_dir="/tmp/vplink-node-install-$$"
  mkdir -p "$tmp_dir"

  info "Downloading Node.js v${ver} for win-${arch}..."
  if ! curl -fsSL --connect-timeout 30 --max-time 300 \
       -o "$tmp_dir/node.zip" "$url"; then
    warn "Download failed: $url"
    rm -rf "$tmp_dir"
    return 1
  fi

  unzip -qo "$tmp_dir/node.zip" -d "$tmp_dir" || {
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

  # Install to a user-accessible location
  local install_dir
  if windows_is_native_shell; then
    install_dir="$USERPROFILE/vplink-tools/node"
  else
    install_dir="$HOME/.local/node"
  fi
  mkdir -p "$install_dir"

  cp -r "$extract_dir/"* "$install_dir/" 2>/dev/null || {
    warn "Failed to copy Node.js files"
    rm -rf "$tmp_dir"
    return 1
  }

  rm -rf "$tmp_dir"

  # Add to PATH for this session
  export PATH="$install_dir:$PATH"

  if windows_node_meets_requirement "$min_major"; then
    log "Node.js v${ver} installed to $install_dir"
    return 0
  fi

  warn "Node.js binary installed but not found in PATH"
  return 1
}

# ───────────────────────────────────────────────────────────────
#  PATH management
# ───────────────────────────────────────────────────────────────

windows_setup_path() {
  set -euo pipefail

  windows_detect_environment || true

  local target_dir="${1:-}"

  if [ -z "$target_dir" ]; then
    # Default: project's local bin
    if [ -n "${HOME:-}" ]; then
      target_dir="$HOME/.local/bin"
    else
      target_dir="/usr/local/bin"
    fi
  fi

  local win_target
  win_target=$(windows_to_winpath "$target_dir" 2>/dev/null || echo "$target_dir")

  # Check if already in PATH
  case ":$PATH:" in
    *":$target_dir:"*) 
      log "Path $target_dir already in PATH"
      return 0
      ;;
  esac

  # Add to current session PATH
  export PATH="$target_dir:$PATH"

  # Persist to user environment via PowerShell (permanent)
  if windows_is_native_shell; then
    _windows_run_ps "[Environment]::SetEnvironmentVariable('Path', '$win_target;' + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')" 2>/dev/null || {
      warn "Could not persist PATH to Windows environment"
      # Fallback: add to .bashrc
      _windows_add_path_to_rc "$target_dir"
    }
    log "Path added to Windows user environment: $win_target"
  elif windows_is_wsl; then
    _windows_add_path_to_rc "$target_dir"
  else
    _windows_add_path_to_rc "$target_dir"
  fi

  return 0
}

_windows_add_path_to_rc() {
  local target_dir="$1"
  local rcfile="$HOME/.bashrc"
  [ -f "$HOME/.zshrc" ] && rcfile="$HOME/.zshrc"

  if grep -q "Added by VPLink" "$rcfile" 2>/dev/null; then
    debug "PATH already configured in $(basename "$rcfile")"
    return 0
  fi

  {
    echo ""
    echo "# Added by VPLink installer"
    echo "export PATH=\"$target_dir:\$PATH\""
  } >> "$rcfile"

  log "Added $target_dir to $(basename "$rcfile")"
}

# ───────────────────────────────────────────────────────────────
#  Long path support
# ───────────────────────────────────────────────────────────────

windows_enable_longpaths() {
  set -euo pipefail

  windows_detect_environment || true

  # Only relevant on Windows native / Git Bash / MSYS2 (not WSL)
  if windows_is_wsl; then
    log "WSL does not need long path configuration"
    return 0
  fi

  # Check if already enabled
  local result
  result=$(_windows_run_ps "(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled" 2>/dev/null || echo "")

  if [ "$result" = "1" ]; then
    log "Long path support already enabled"
    return 0
  fi

  # Enable via registry
  info "Enabling Windows long path support (>260 chars)..."
  _windows_run_ps "New-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' -Name 'LongPathsEnabled' -Value 1 -PropertyType DWORD -Force" 2>/dev/null || {
    warn "Could not enable long paths via registry"
    warn "You may need to run as Administrator or set manually:"
    warn "  HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\LongPathsEnabled = 1"
    return 0
  }

  # Enable via Group Policy as well
  _windows_run_ps "New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System' -Name 'LongPathsEnabled' -Value 1 -PropertyType DWORD -Force" 2>/dev/null || true

  log "Long path support enabled (reboot may be required)"
}

# ───────────────────────────────────────────────────────────────
#  Cleanup
# ───────────────────────────────────────────────────────────────

windows_cleanup() {
  set -euo pipefail

  info "Cleaning up..."

  rm -rf /tmp/vplink-node-install-* 2>/dev/null || true

  if command -v choco &>/dev/null; then
    choco clean all 2>/dev/null || true
  fi

  if command -v scoop &>/dev/null; then
    scoop cache rm * 2>/dev/null || true
  fi

  log "Windows cleanup complete"
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
