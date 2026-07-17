#!/usr/bin/env bash
# installer/commands/install.sh — Main installation command
# Orchestrates the full VPLink 3.0 installation flow.
# Usage: cmd_install [--noninteractive] [--skip-deps] [--skip-node] [--skip-playwright]

TOTAL_STEPS=12

cmd_install() {
  set -euo pipefail

  local NONINTERACTIVE=false
  local SKIP_DEPS=false
  local SKIP_NODE=false
  local SKIP_PLAYWRIGHT=false

  while [ $# -gt 0 ]; do
    case "$1" in
      --noninteractive) NONINTERACTIVE=true ;;
      --skip-deps)      SKIP_DEPS=true ;;
      --skip-node)      SKIP_NODE=true ;;
      --skip-playwright) SKIP_PLAYWRIGHT=true ;;
      *) log_warn "Unknown install option: $1" ;;
    esac
    shift
  done

  ui_welcome

  local STEP=0
  local ERRORS=()

  rollback_init

  # ── Step 1: Welcome + environment detection ────────────────
  STEP=1
  ui_progress_init "$TOTAL_STEPS" "Detecting environment"
  rollback_push "env detection"

  if state_is_done "env_detect"; then
    log_info "  Environment already detected (cached)"
    ui_progress_update "$STEP" "Detecting environment" "done"
  else
    ui_spinner_start "Detecting platform, OS, architecture..."
    platform_detect_all
    ui_spinner_stop

    log_info "  OS:        ${OS:-unknown}"
    log_info "  Distro:    ${DISTRO:-unknown}"
    log_info "  Arch:      ${ARCH:-unknown}"
    log_info "  PkgMgr:    ${PKG_MANAGER:-unknown}"
    log_info "  Root:      ${IS_ROOT:-false}"
    log_info "  Docker:    ${IS_DOCKER:-false}"
    log_info "  WSL:       ${IS_WSL:-false}"
    log_info "  Termux:    ${IS_TERMUX:-false}"

    state_mark_done "env_detect"
    ui_progress_update "$STEP" "Detecting environment" "done"
  fi

  # ── Step 2: Check prerequisites ────────────────────────────
  STEP=2
  ui_progress_update "$STEP" "Checking prerequisites" "running"
  rollback_push "prerequisites"

  local PREREQ_ERRORS=()

  if ! has_cmd git; then
    PREREQ_ERRORS+=("git not found")
  fi

  if ! has_cmd curl && ! has_cmd wget; then
    PREREQ_ERRORS+=("Neither curl nor wget found")
  fi

  local DISK_AVAIL
  DISK_AVAIL=$(df -BM "${HOME}" | awk 'NR==2{print $4}' | tr -d 'M')
  if [ "${DISK_AVAIL:-0}" -lt 500 ]; then
    PREREQ_ERRORS+=("Insufficient disk space: ${DISK_AVAIL}MB (need 500MB+)")
  fi

  if [ ${#PREREQ_ERRORS[@]} -gt 0 ]; then
    for err in "${PREREQ_ERRORS[@]}"; do
      log_fail "$err"
    done
    rollback_execute
    return 1
  fi

  state_mark_done "prerequisites"
  ui_progress_update "$STEP" "Checking prerequisites" "done"

  # ── Step 3: Install system dependencies ────────────────────
  STEP=3
  rollback_push "system_deps"

  if [ "$SKIP_DEPS" = true ]; then
    log_info "  Skipping system dependencies (--skip-deps)"
    ui_progress_update "$STEP" "Install system dependencies" "skip"
  elif state_is_done "system_deps"; then
    log_info "  System dependencies already installed (cached)"
    ui_progress_update "$STEP" "Install system dependencies" "done"
  else
    ui_progress_update "$STEP" "Installing system dependencies" "running"
    ui_spinner_start "Installing packages for ${PKG_MANAGER}..."

    pkg_update

    local PKGS_TO_INSTALL=()

    if [ "${IS_TERMUX:-false}" != true ]; then
      PKGS_TO_INSTALL+=(git curl wget build-essential)
    fi

    case "${DISTRO_FAMILY:-}" in
      debian|ubuntu)
        PKGS_TO_INSTALL+=(ca-certificates gnupg lsb-release xvfb x11vnc)
        ;;
      fedora|rhel|centos)
        PKGS_TO_INSTALL+=(xorg-x11-server-Xvfb x11vnc)
        ;;
      arch|manjaro)
        PKGS_TO_INSTALL+=(xorg-xvfb x11vnc)
        ;;
      alpine)
        PKGS_TO_INSTALL+=(xvfb-run x11vnc)
        ;;
      *)
        if [ "${IS_TERMUX:-false}" = true ]; then
          PKGS_TO_INSTALL+=(turbovnc)
        fi
        ;;
    esac

    if [ ${#PKGS_TO_INSTALL[@]} -gt 0 ]; then
      pkg_install "${PKGS_TO_INSTALL[@]}" || {
        log_warn "Some packages may not be available on this platform"
      }
    fi

    ui_spinner_stop
    state_mark_done "system_deps"
    ui_progress_update "$STEP" "Install system dependencies" "done"
  fi

  # ── Step 4: Install Node.js ────────────────────────────────
  STEP=4
  rollback_push "nodejs"

  if [ "$SKIP_NODE" = true ]; then
    log_info "  Skipping Node.js (--skip-node)"
    ui_progress_update "$STEP" "Install Node.js" "skip"
  elif state_is_done "nodejs"; then
    log_info "  Node.js already installed (cached)"
    ui_progress_update "$STEP" "Install Node.js" "done"
  else
    ui_progress_update "$STEP" "Installing Node.js" "running"
    ui_spinner_start "Installing Node.js 18+..."

    _install_nodejs

    ui_spinner_stop

    local NODE_VER
    NODE_VER=$(node --version 2>/dev/null | tr -d 'v' | cut -d. -f1)
    if [ -z "$NODE_VER" ] || [ "${NODE_VER:-0}" -lt 18 ]; then
      log_fail "Node.js >= 18 required (got: $(node --version 2>/dev/null || echo 'not found'))"
      rollback_execute
      return 1
    fi

    state_mark_done "nodejs"
    ui_progress_update "$STEP" "Install Node.js" "done"
  fi

  # ── Step 5: Setup project directory ────────────────────────
  STEP=5
  rollback_push "project_dir"

  if state_is_done "project_dir"; then
    log_info "  Project directory already set up (cached)"
    ui_progress_update "$STEP" "Setup project directory" "done"
  else
    ui_progress_update "$STEP" "Setting up project directory" "running"
    ui_spinner_start "Cloning/pulling repository..."

    local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"

    if [ -d "$INSTALL_DIR/.git" ]; then
      log_info "  Repository exists, pulling latest..."
      git -C "$INSTALL_DIR" fetch --all --quiet 2>/dev/null || true
      git -C "$INSTALL_DIR" pull --ff-only --quiet 2>/dev/null || {
        log_warn "  Could not fast-forward; resetting to origin/main"
        git -C "$INSTALL_DIR" reset --hard origin/main --quiet 2>/dev/null || true
      }
    else
      local REPO_URL="${VPLINK_REPO:-https://github.com/adittaya/VPLINK-3.0.git}"
      git clone "$REPO_URL" "$INSTALL_DIR" --quiet 2>/dev/null
    fi

    ui_spinner_stop
    state_mark_done "project_dir"
    ui_progress_update "$STEP" "Setup project directory" "done"
  fi

  # ── Step 6: Install npm dependencies ───────────────────────
  STEP=6
  rollback_push "npm_deps"

  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"

  if state_is_done "npm_deps"; then
    log_info "  npm dependencies already installed (cached)"
    ui_progress_update "$STEP" "Install npm dependencies" "done"
  else
    ui_progress_update "$STEP" "Installing npm dependencies" "running"
    ui_spinner_start "npm install..."

    (cd "$INSTALL_DIR" && npm install --production 2>&1) || {
      log_warn "  Retrying npm install..."
      (cd "$INSTALL_DIR" && npm install --production 2>&1) || {
        ui_spinner_stop
        log_fail "npm install failed"
        rollback_execute
        return 1
      }
    }

    ui_spinner_stop
    state_mark_done "npm_deps"
    ui_progress_update "$STEP" "Install npm dependencies" "done"
  fi

  # ── Step 7: Install Playwright Chromium ────────────────────
  STEP=7
  rollback_push "playwright"

  if [ "$SKIP_PLAYWRIGHT" = true ]; then
    log_info "  Skipping Playwright (--skip-playwright)"
    ui_progress_update "$STEP" "Install Playwright" "skip"
  elif [ "${IS_TERMUX:-false}" = true ]; then
    log_info "  Playwright uses external Chromium on Termux"
    ui_progress_update "$STEP" "Install Playwright" "skip"
  elif state_is_done "playwright"; then
    log_info "  Playwright already installed (cached)"
    ui_progress_update "$STEP" "Install Playwright" "done"
  else
    ui_progress_update "$STEP" "Installing Playwright Chromium" "running"
    ui_spinner_start "Installing Chromium via Playwright..."

    local PLAYWRIGHT_DIR="$INSTALL_DIR/node_modules/playwright"
    if [ -d "$PLAYWRIGHT_DIR" ]; then
      (cd "$INSTALL_DIR" && npx playwright install chromium 2>&1) || {
        log_warn "  Playwright Chromium install failed; will try system Chromium"
      }
    fi

    ui_spinner_stop
    state_mark_done "playwright"
    ui_progress_update "$STEP" "Install Playwright Chromium" "done"
  fi

  # ── Step 8: Create global CLI command ──────────────────────
  STEP=8
  rollback_push "global_cmd"

  if state_is_done "global_cmd"; then
    log_info "  Global command already created (cached)"
    ui_progress_update "$STEP" "Create global CLI command" "done"
  else
    ui_progress_update "$STEP" "Creating global CLI command" "running"
    ui_spinner_start "Setting up vplink3.0 command..."

    _create_global_command "$INSTALL_DIR"

    ui_spinner_stop
    state_mark_done "global_cmd"
    ui_progress_update "$STEP" "Create global CLI command" "done"
  fi

  # ── Step 9: Setup credentials (interactive) ────────────────
  STEP=9
  rollback_push "credentials"

  if [ "$NONINTERACTIVE" = true ]; then
    log_info "  Skipping credential setup (--noninteractive)"
    ui_progress_update "$STEP" "Setup credentials" "skip"
  elif state_is_done "credentials"; then
    log_info "  Credentials already configured (cached)"
    ui_progress_update "$STEP" "Setup credentials" "done"
  else
    ui_progress_update "$STEP" "Setting up credentials" "running"
    ui_spinner_start "Configuring credentials..."

    _setup_credentials

    ui_spinner_stop
    state_mark_done "credentials"
    ui_progress_update "$STEP" "Setup credentials" "done"
  fi

  # ── Step 10: Verify installation ───────────────────────────
  STEP=10
  rollback_push "verify"

  ui_progress_update "$STEP" "Verifying installation" "running"
  ui_spinner_start "Running verification checks..."

  local VERIFY_ERRORS
  VERIFY_ERRORS=$(verify_installation 2>&1) || true
  local VERIFY_EXIT=$?

  ui_spinner_stop

  if [ "$VERIFY_EXIT" -ne 0 ]; then
    log_warn "  Some verification checks failed:"
    echo "$VERIFY_ERRORS" | while IFS= read -r line; do
      log_warn "    $line"
    done
    ERRORS+=("verification_partial")
  fi

  state_mark_done "verify"
  ui_progress_update "$STEP" "Verifying installation" "done"

  # ── Step 11: Save final state ──────────────────────────────
  STEP=11
  rollback_push "final_state"

  ui_progress_update "$STEP" "Saving installation state" "running"

  config_set "install.version" "3.0.0"
  config_set "install.date" "$(date -Iseconds)"
  config_set "install.dir" "$INSTALL_DIR"
  config_set "install.node_version" "$(node --version 2>/dev/null || echo 'unknown')"
  config_set "install.os" "${OS:-unknown}"
  config_set "install.distro" "${DISTRO:-unknown}"

  state_mark_done "final_state"
  ui_progress_update "$STEP" "Saving installation state" "done"

  # ── Step 12: Print summary ─────────────────────────────────
  STEP=12
  rollback_push "summary"

  ui_progress_update "$STEP" "Installation complete" "done"

  ui_summary \
    "VPLink 3.0 installed successfully" \
    "Version: 3.0.0" \
    "Directory: ${INSTALL_DIR}" \
    "Command: vplink3.0" \
    "Config: $(config_path)" \
    "Logs: ${LOG_DIR:-~/.vplink3.0/logs}"

  rollback_clear

  log_ok "Installation complete!"
  return 0
}

# ── Internal helpers ──────────────────────────────────────────

_install_nodejs() {
  set -euo pipefail

  if has_cmd node; then
    local NODE_MAJOR
    NODE_MAJOR=$(node --version | tr -d 'v' | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
      log_ok "Node.js $(node --version) already satisfies >= 18"
      return 0
    fi
  fi

  if [ "${IS_TERMUX:-false}" = true ]; then
    if has_cmd pkg; then
      pkg install -y nodejs 2>/dev/null || true
      return 0
    fi
  fi

  if command -v nvm &>/dev/null; then
    nvm install 18 2>/dev/null || true
    return 0
  fi

  if [ -d "$HOME/.nvm" ]; then
    export NVM_DIR="$HOME/.nvm"
    # shellcheck disable=SC1091
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
    nvm install 18 2>/dev/null || true
    return 0
  fi

  case "${PKG_MANAGER:-}" in
    apt-get)
      local NODE_MAJOR_CURRENT=0
      if has_cmd node; then
        NODE_MAJOR_CURRENT=$(node --version 2>/dev/null | tr -d 'v' | cut -d. -f1)
      fi
      if [ "$NODE_MAJOR_CURRENT" -lt 18 ] 2>/dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_18.x | $SUDO bash - 2>/dev/null || true
        $SUDO apt-get install -y nodejs 2>/dev/null || true
      fi
      ;;
    dnf|yum)
      curl -fsSL https://rpm.nodesource.com/setup_18.x | $SUDO bash - 2>/dev/null || true
      $SUDO "$PKG_MANAGER" install -y nodejs 2>/dev/null || true
      ;;
    pacman)
      $SUDO pacman -Sy --noconfirm nodejs npm 2>/dev/null || true
      ;;
    apk)
      $SUDO apk add --no-cache nodejs npm 2>/dev/null || true
      ;;
    brew)
      brew install node@18 2>/dev/null || brew install node 2>/dev/null || true
      ;;
    *)
      log_warn "Cannot auto-install Node.js for ${PKG_MANAGER:-unknown} package manager"
      log_warn "Please install Node.js >= 18 manually"
      return 1
      ;;
  esac
}

_create_global_command() {
  set -euo pipefail

  local INSTALL_DIR="$1"
  local BIN_DIR="$HOME/.local/bin"
  local CMD_PATH="$BIN_DIR/vplink3.0"

  mkdir -p "$BIN_DIR"

  cat > "$CMD_PATH" <<WRAPPER
#!/usr/bin/env bash
exec node "$INSTALL_DIR/automation.js" "\$@"
WRAPPER

  chmod +x "$CMD_PATH"

  local PROFILE
  PROFILE=$(env_get_profile)

  if [ -f "$PROFILE" ]; then
    if ! grep -q "HOME/.local/bin" "$PROFILE" 2>/dev/null; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$PROFILE"
      log_info "  Added $BIN_DIR to PATH in $PROFILE"
    fi
  fi

  export PATH="$BIN_DIR:$PATH"

  log_ok "Global command created: $CMD_PATH"
}

_setup_credentials() {
  set -euo pipefail

  local CRED_FILE
  CRED_FILE=$(config_path)

  mkdir -p "$(dirname "$CRED_FILE")"

  if [ -f "$CRED_FILE" ]; then
    log_info "  Config file exists at $CRED_FILE"
    if [ "${NONINTERACTIVE:-false}" = true ]; then
      return 0
    fi
    if ui_confirm "Config file exists. Overwrite?" "n"; then
      : # continue
    else
      log_info "  Keeping existing config"
      return 0
    fi
  fi

  local DEFAULT_CONFIG='{
  "profile": "default",
  "browser": {
    "headless": true,
    "timeout": 60000
  },
  "proxy": {
    "enabled": false,
    "source": "supabase"
  },
  "vnc": {
    "enabled": false,
    "port": 5900
  }
}'

  echo "$DEFAULT_CONFIG" > "$CRED_FILE"
  log_ok "Default config written to $CRED_FILE"
}
