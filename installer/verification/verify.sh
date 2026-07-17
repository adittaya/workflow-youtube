#!/usr/bin/env bash
# installer/verification/verify.sh — Post-install verification
# Checks all components and reports status.
# Usage: verify_installation (returns error count)

verify_installation() {
  set -euo pipefail

  local ERRORS=0
  local WARNINGS=0
  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"
  local CONFIG_FILE
  CONFIG_FILE=$(config_path 2>/dev/null || echo "$HOME/.vplink3.0/config.json")

  # ── Table header ────────────────────────────────────────────
  printf "\n\033[1mVPLink 3.0 — Installation Verification\033[0m\n\n"
  printf "\033[1m%-16s %-10s %-42s\033[0m\n" "Component" "Status" "Version / Detail"
  printf "─────────────── ────────── ──────────────────────────────────────\n"

  # ── Git ─────────────────────────────────────────────────────
  if has_cmd git; then
    local GIT_VER
    GIT_VER=$(git --version 2>/dev/null | awk '{print $3}' || echo "unknown")
    _verify_row "Git" "pass" "$GIT_VER"
  else
    _verify_row "Git" "fail" "not installed"
    ERRORS=$((ERRORS + 1))
  fi

  # ── Node.js ─────────────────────────────────────────────────
  if has_cmd node; then
    local NODE_VER
    NODE_VER=$(node --version 2>/dev/null || echo "unknown")
    local NODE_MAJOR
    NODE_MAJOR=$(echo "$NODE_VER" | tr -d 'v' | cut -d. -f1)
    if [ "${NODE_MAJOR:-0}" -ge 18 ]; then
      _verify_row "Node.js" "pass" "$NODE_VER"
    else
      _verify_row "Node.js" "warn" "$NODE_VER (need >= 18)"
      WARNINGS=$((WARNINGS + 1))
    fi
  else
    _verify_row "Node.js" "fail" "not installed"
    ERRORS=$((ERRORS + 1))
  fi

  # ── npm ─────────────────────────────────────────────────────
  if has_cmd npm; then
    local NPM_VER
    NPM_VER=$(npm --version 2>/dev/null || echo "unknown")
    _verify_row "npm" "pass" "$NPM_VER"
  else
    _verify_row "npm" "fail" "not installed"
    ERRORS=$((ERRORS + 1))
  fi

  # ── Chromium ────────────────────────────────────────────────
  if [ "${IS_TERMUX:-false}" = true ]; then
    _verify_row "Chromium" "skip" "managed externally (Termux)"
  else
    local CHROMIUM_FOUND=""
    local CHROMIUM_PATHS=(
      /usr/bin/chromium
      /usr/bin/chromium-browser
      /usr/bin/google-chrome
      /snap/bin/chromium
    )

    for candidate in "${CHROMIUM_PATHS[@]}"; do
      if [ -x "$candidate" ]; then
        CHROMIUM_FOUND="$candidate"
        break
      fi
    done

    if [ -z "$CHROMIUM_FOUND" ] && [ -d "$INSTALL_DIR/node_modules" ]; then
      CHROMIUM_FOUND=$(find "$INSTALL_DIR/node_modules" -path "*/chromium*/chrome-linux/chrome" -type f 2>/dev/null | head -1 || true)
    fi

    if [ -n "$CHROMIUM_FOUND" ]; then
      _verify_row "Chromium" "pass" "$CHROMIUM_FOUND"
    else
      _verify_row "Chromium" "fail" "not found"
      ERRORS=$((ERRORS + 1))
    fi
  fi

  # ── Xvfb (Linux only) ──────────────────────────────────────
  if [ "${IS_TERMUX:-false}" != true ] && [ "${OS:-}" != "macos" ] && [ "${OS:-}" != "windows" ]; then
    if has_cmd Xvfb || has_cmd xvfb-run; then
      local XVFB_VER
      XVFB_VER=$(Xvfb -version 2>/dev/null | head -1 | awk '{print $NF}' || echo "present")
      _verify_row "Xvfb" "pass" "$XVFB_VER"
    else
      _verify_row "Xvfb" "fail" "not installed"
      ERRORS=$((ERRORS + 1))
    fi
  fi

  # ── x11vnc (Linux only) ────────────────────────────────────
  if [ "${IS_TERMUX:-false}" != true ] && [ "${OS:-}" != "macos" ] && [ "${OS:-}" != "windows" ]; then
    if has_cmd x11vnc; then
      local VNC_VER
      VNC_VER=$(x11vnc --version 2>/dev/null | head -1 | awk '{print $NF}' || echo "present")
      _verify_row "x11vnc" "pass" "$VNC_VER"
    else
      _verify_row "x11vnc" "fail" "not installed"
      ERRORS=$((ERRORS + 1))
    fi
  fi

  # ── Project files ───────────────────────────────────────────
  local REQUIRED_FILES=(
    automation.js
    config.js
    proxy-rotator.js
    profile-generator.js
    vplink3.0.sh
    vplink-desktop.sh
    install.sh
    package.json
  )

  local MISSING_FILES=()
  for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$INSTALL_DIR/$f" ]; then
      MISSING_FILES+=("$f")
    fi
  done

  if [ ${#MISSING_FILES[@]} -eq 0 ]; then
    _verify_row "Project files" "pass" "${#REQUIRED_FILES[@]}/${#REQUIRED_FILES[@]} present"
  elif [ ${#MISSING_FILES[@]} -lt ${#REQUIRED_FILES[@]} ]; then
    _verify_row "Project files" "warn" "missing: ${MISSING_FILES[*]}"
    WARNINGS=$((WARNINGS + 1))
  else
    _verify_row "Project files" "fail" "project directory not found"
    ERRORS=$((ERRORS + 1))
  fi

  # ── node_modules ────────────────────────────────────────────
  if [ -d "$INSTALL_DIR/node_modules" ]; then
    local PKG_COUNT
    PKG_COUNT=$(find "$INSTALL_DIR/node_modules" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    if [ "$PKG_COUNT" -gt 0 ]; then
      _verify_row "node_modules" "pass" "$PKG_COUNT packages installed"
    else
      _verify_row "node_modules" "warn" "directory exists but empty"
      WARNINGS=$((WARNINGS + 1))
    fi
  else
    _verify_row "node_modules" "fail" "not installed"
    ERRORS=$((ERRORS + 1))
  fi

  # ── Global command ──────────────────────────────────────────
  local GLOBAL_FOUND=""
  for candidate in "$HOME/.local/bin/vplink3.0" /usr/local/bin/vplink3.0 /usr/bin/vplink3.0; do
    if [ -x "$candidate" ]; then
      GLOBAL_FOUND="$candidate"
      break
    fi
  done

  if [ -n "$GLOBAL_FOUND" ]; then
    _verify_row "Global command" "pass" "$GLOBAL_FOUND"
  else
    _verify_row "Global command" "fail" "not found"
    ERRORS=$((ERRORS + 1))
  fi

  # ── Config file ─────────────────────────────────────────────
  if [ -f "$CONFIG_FILE" ]; then
    local CFG_SIZE
    CFG_SIZE=$(wc -c < "$CONFIG_FILE" 2>/dev/null | tr -d ' ' || echo "?")
    if [ "$CFG_SIZE" -gt 2 ] 2>/dev/null; then
      _verify_row "Config file" "pass" "$CONFIG_FILE ($CFG_SIZE bytes)"
    else
      _verify_row "Config file" "warn" "exists but empty"
      WARNINGS=$((WARNINGS + 1))
    fi
  else
    _verify_row "Config file" "fail" "not found"
    ERRORS=$((ERRORS + 1))
  fi

  printf "\n"

  # ── Summary ─────────────────────────────────────────────────
  if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
    printf "\033[0;32mAll checks passed!\033[0m\n\n"
  elif [ "$ERRORS" -eq 0 ]; then
    printf "\033[1;33mPassed with %d warning(s)\033[0m\n\n" "$WARNINGS"
  else
    printf "\033[0;31mFailed: %d error(s), %d warning(s)\033[0m\n\n" "$ERRORS" "$WARNINGS"
  fi

  return "$ERRORS"
}

_verify_row() {
  local NAME="$1"
  local STATUS="$2"
  local DETAIL="$3"

  local COLOR SYMBOL NC="\033[0m"
  case "$STATUS" in
    pass)
      COLOR="\033[0;32m"
      SYMBOL="✓"
      ;;
    warn)
      COLOR="\033[1;33m"
      SYMBOL="⚠"
      ;;
    skip)
      COLOR="\033[0;36m"
      SYMBOL="○"
      ;;
    *)
      COLOR="\033[0;31m"
      SYMBOL="✗"
      ;;
  esac

  printf "%-16s ${COLOR}%-10s${NC} %-42s\n" "$NAME" " $SYMBOL $STATUS" "$DETAIL"
}
