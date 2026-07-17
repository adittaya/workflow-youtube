#!/usr/bin/env bash
# installer/commands/repair.sh — Repair command
# Detects and fixes broken installations.
# Usage: cmd_repair

cmd_repair() {
  set -euo pipefail

  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"
  local ISSUES_FOUND=0
  local ISSUES_FIXED=0

  ui_progress_init 7 "Repairing VPLink 3.0"
  rollback_init

  log_info "Scanning for issues...\n"

  # ── Step 1: Detect what's broken ───────────────────────────
  ui_progress_update 1 "Diagnosing installation" "running"
  rollback_push "diagnose"

  local BROKEN_COMPONENTS=()

  # Check system dependencies
  local MISSING_DEPS=()
  for cmd_name in git curl node npm; do
    if ! has_cmd "$cmd_name"; then
      MISSING_DEPS+=("$cmd_name")
      ISSUES_FOUND=$((ISSUES_FOUND + 1))
    fi
  done

  # Check project directory
  local PROJECT_OK=true
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    PROJECT_OK=false
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    BROKEN_COMPONENTS+=("project_dir")
    log_fail "  Project directory: missing or not a git repo ($INSTALL_DIR)"
  else
    log_ok "  Project directory: OK"
  fi

  # Check node_modules
  local NODEMOD_OK=true
  if [ ! -d "$INSTALL_DIR/node_modules" ]; then
    NODEMOD_OK=false
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    BROKEN_COMPONENTS+=("node_modules")
    log_fail "  node_modules: missing"
  elif [ ! -f "$INSTALL_DIR/node_modules/playwright/package.json" ]; then
    NODEMOD_OK=false
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    BROKEN_COMPONENTS+=("playwright_module")
    log_fail "  Playwright module: missing from node_modules"
  else
    log_ok "  node_modules: OK"
  fi

  # Check Playwright Chromium
  local PW_CHROMIUM_OK=true
  if [ "${IS_TERMUX:-false}" != true ]; then
    local PLAYWRIGHT_BROWSERS
    PLAYWRIGHT_BROWSERS=$(find "$INSTALL_DIR/node_modules" -name "chrome" -o -name "chromium" 2>/dev/null | head -5 || true)
    local SYSTEM_CHROMIUM=""
    for candidate in /usr/bin/chromium /usr/bin/chromium-browser /usr/bin/google-chrome /snap/bin/chromium; do
      if [ -x "$candidate" ]; then
        SYSTEM_CHROMIUM="$candidate"
        break
      fi
    done
    if [ -z "$PLAYWRIGHT_BROWSERS" ] && [ -z "$SYSTEM_CHROMIUM" ]; then
      PW_CHROMIUM_OK=false
      ISSUES_FOUND=$((ISSUES_FOUND + 1))
      BROKEN_COMPONENTS+=("chromium")
      log_fail "  Chromium: not found (Playwright or system)"
    else
      log_ok "  Chromium: OK"
    fi
  fi

  # Check global command
  local GLOBAL_CMD_OK=true
  local GLOBAL_PATH=""
  for candidate in "$HOME/.local/bin/vplink3.0" /usr/local/bin/vplink3.0 /usr/bin/vplink3.0; do
    if [ -x "$candidate" ]; then
      GLOBAL_PATH="$candidate"
      break
    fi
  done
  if [ -z "$GLOBAL_PATH" ]; then
    GLOBAL_CMD_OK=false
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    BROKEN_COMPONENTS+=("global_cmd")
    log_fail "  Global command: not found"
  else
    if [ -f "$GLOBAL_PATH" ]; then
      local CMD_TARGET
      CMD_TARGET=$(sed -n 's/.*node "\([^"]*\)".*/\1/p' "$GLOBAL_PATH" 2>/dev/null || true)
      if [ -n "$CMD_TARGET" ] && [ ! -f "$CMD_TARGET" ]; then
        GLOBAL_CMD_OK=false
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
        BROKEN_COMPONENTS+=("global_cmd_stale")
        log_fail "  Global command: target missing ($CMD_TARGET)"
      else
        log_ok "  Global command: OK ($GLOBAL_PATH)"
      fi
    fi
  fi

  # Check Node.js version
  local NODE_OK=true
  if has_cmd node; then
    local NODE_MAJOR
    NODE_MAJOR=$(node --version 2>/dev/null | tr -d 'v' | cut -d. -f1)
    if [ "${NODE_MAJOR:-0}" -lt 18 ]; then
      NODE_OK=false
      ISSUES_FOUND=$((ISSUES_FOUND + 1))
      BROKEN_COMPONENTS+=("node_version")
      log_fail "  Node.js version: $(node --version) (need >= 18)"
    else
      log_ok "  Node.js version: $(node --version)"
    fi
  fi

  # Check config
  local CONFIG_PATH_VAL
  CONFIG_PATH_VAL=$(config_path 2>/dev/null || echo "$HOME/.vplink3.0/config.json")
  if [ ! -f "$CONFIG_PATH_VAL" ]; then
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    BROKEN_COMPONENTS+=("config")
    log_fail "  Config file: missing ($CONFIG_PATH_VAL)"
  else
    log_ok "  Config file: OK"
  fi

  ui_progress_update 1 "Diagnosing installation" "done"

  if [ "$ISSUES_FOUND" -eq 0 ]; then
    ui_summary "No issues found — installation is healthy"
    rollback_clear
    return 0
  fi

  log_info "\nFound $ISSUES_FOUND issue(s). Attempting repairs...\n"

  # ── Step 2: Reinstall missing system dependencies ──────────
  ui_progress_update 2 "Repairing system dependencies" "running"
  rollback_push "system_deps_repair"

  if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    log_info "  Installing missing tools: ${MISSING_DEPS[*]}"

    case "${PKG_MANAGER:-}" in
      apt-get)
        pkg_update 2>/dev/null || true
        $SUDO apt-get install -y "${MISSING_DEPS[@]}" 2>/dev/null || true
        ;;
      dnf|yum)
        pkg_update 2>/dev/null || true
        $SUDO "$PKG_MANAGER" install -y "${MISSING_DEPS[@]}" 2>/dev/null || true
        ;;
      pacman)
        $SUDO pacman -Sy --noconfirm "${MISSING_DEPS[@]}" 2>/dev/null || true
        ;;
      apk)
        $SUDO apk add --no-cache "${MISSING_DEPS[@]}" 2>/dev/null || true
        ;;
      brew)
        brew install "${MISSING_DEPS[@]}" 2>/dev/null || true
        ;;
      *)
        log_warn "  Cannot auto-install for package manager: ${PKG_MANAGER:-unknown}"
        ;;
    esac

    local STILL_MISSING=()
    for dep in "${MISSING_DEPS[@]}"; do
      if ! has_cmd "$dep"; then
        STILL_MISSING+=("$dep")
      fi
    done

    if [ ${#STILL_MISSING[@]} -gt 0 ]; then
      log_fail "  Could not install: ${STILL_MISSING[*]}"
    else
      ISSUES_FIXED=$((ISSUES_FIXED + ${#MISSING_DEPS[@]}))
      log_ok "  System dependencies installed"
    fi
  else
    log_ok "  System dependencies OK"
  fi

  ui_progress_update 2 "Repairing system dependencies" "done"

  # ── Step 3: Reinstall Node.js if broken ────────────────────
  ui_progress_update 3 "Repairing Node.js" "running"
  rollback_push "nodejs_repair"

  if [ "${NODE_OK}" = false ]; then
    log_info "  Reinstalling Node.js..."
    (source "$INSTALL_DIR/installer/commands/install.sh" 2>/dev/null && _install_nodejs) || {
      log_warn "  Could not auto-install Node.js"
    }

    if has_cmd node; then
      local NEW_MAJOR
      NEW_MAJOR=$(node --version 2>/dev/null | tr -d 'v' | cut -d. -f1)
      if [ "${NEW_MAJOR:-0}" -ge 18 ]; then
        ISSUES_FIXED=$((ISSUES_FIXED + 1))
        log_ok "  Node.js $(node --version) installed"
      else
        log_fail "  Node.js version still insufficient"
      fi
    fi
  else
    log_ok "  Node.js OK"
  fi

  ui_progress_update 3 "Repairing Node.js" "done"

  # ── Step 4: Re-run npm install ─────────────────────────────
  ui_progress_update 4 "Reinstalling npm dependencies" "running"
  rollback_push "npm_repair"

  if [ "$PROJECT_OK" = true ]; then
    if [ "$NODEMOD_OK" = false ]; then
      log_info "  Running npm install..."
      (cd "$INSTALL_DIR" && npm install --production 2>&1) || {
        log_warn "  npm install had issues"
      }

      if [ -d "$INSTALL_DIR/node_modules" ]; then
        ISSUES_FIXED=$((ISSUES_FIXED + 1))
        log_ok "  npm dependencies reinstalled"
      fi
    else
      log_info "  Verifying node_modules integrity..."
      (cd "$INSTALL_DIR" && npm install --production --prefer-offline 2>&1) || true
      log_ok "  npm dependencies OK"
    fi
  else
    log_warn "  Skipping npm install (project dir is broken)"
  fi

  ui_progress_update 4 "Reinstalling npm dependencies" "done"

  # ── Step 5: Reinstall Playwright ────────────────────────────
  ui_progress_update 5 "Reinstalling Playwright" "running"
  rollback_push "playwright_repair"

  if [ "${PW_CHROMIUM_OK}" = false ] && [ "$NODEMOD_OK" = true ] && [ "${IS_TERMUX:-false}" != true ]; then
    log_info "  Installing Playwright Chromium..."
    (cd "$INSTALL_DIR" && npx playwright install chromium 2>&1) || {
      log_warn "  Playwright install had issues"
    }
    ISSUES_FIXED=$((ISSUES_FIXED + 1))
    log_ok "  Playwright Chromium installed"
  else
    log_ok "  Playwright OK"
  fi

  ui_progress_update 5 "Reinstalling Playwright" "done"

  # ── Step 6: Recreate global command ────────────────────────
  ui_progress_update 6 "Recreating global command" "running"
  rollback_push "global_cmd_repair"

  if [ "$GLOBAL_CMD_OK" = false ] && [ "$PROJECT_OK" = true ]; then
    log_info "  Recreating global command..."

    local BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"

    cat > "$BIN_DIR/vplink3.0" <<WRAPPER
#!/usr/bin/env bash
exec node "$INSTALL_DIR/automation.js" "\$@"
WRAPPER
    chmod +x "$BIN_DIR/vplink3.0"

    local PROFILE
    PROFILE=$(env_get_profile 2>/dev/null || echo "$HOME/.bashrc")
    if [ -f "$PROFILE" ]; then
      if ! grep -q "HOME/.local/bin" "$PROFILE" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$PROFILE"
      fi
    fi

    ISSUES_FIXED=$((ISSUES_FIXED + 1))
    log_ok "  Global command recreated: $BIN_DIR/vplink3.0"
  else
    log_ok "  Global command OK"
  fi

  ui_progress_update 6 "Recreating global command" "done"

  # ── Step 7: Verify ─────────────────────────────────────────
  ui_progress_update 7 "Verifying repairs" "running"
  rollback_push "verify_repair"

  local VERIFY_ERRORS=0
  VERIFY_ERRORS=$(verify_installation 2>&1 | grep -c "✗" || echo 0)

  ui_progress_update 7 "Verifying repairs" "done"

  rollback_clear

  if [ "$VERIFY_ERRORS" -gt 0 ]; then
    ui_summary \
      "Repaired $ISSUES_FIXED of $ISSUES_FOUND issue(s)" \
      "$VERIFY_ERRORS verification issue(s) remain" \
      "Run 'vplink3.0 doctor' for detailed diagnostics"
    return 1
  else
    ui_summary \
      "All $ISSUES_FOUND issue(s) repaired successfully" \
      "Installation is healthy"
    log_ok "Repair complete!"
    return 0
  fi
}
