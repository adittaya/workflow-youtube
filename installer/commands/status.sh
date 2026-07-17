#!/usr/bin/env bash
# installer/commands/status.sh — Status command
# Shows detailed installation status for all components.
# Usage: cmd_status

cmd_status() {
  set -euo pipefail

  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"
  local CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/.vplink3.0"
  [ -d "$HOME/.vplink3.0" ] && CONFIG_DIR="$HOME/.vplink3.0"
  local CONFIG_FILE="$CONFIG_DIR/config.json"
  local LOG_DIR="$CONFIG_DIR/logs"

  local INSTALLED_VERSION="unknown"
  local INSTALL_DATE="unknown"
  if [ -f "$CONFIG_FILE" ]; then
    INSTALLED_VERSION=$(config_get "install.version" 2>/dev/null || echo "unknown")
    INSTALL_DATE=$(config_get "install.date" 2>/dev/null || echo "unknown")
  fi

  printf "\n"
  printf "\033[1mVPLink 3.0 — Installation Status\033[0m\n"
  printf "══════════════════════════════════════════════════════════════\n\n"

  # ── Version info ────────────────────────────────────────────
  printf "\033[1mVersion:\033[0m      %s\n" "$INSTALLED_VERSION"
  printf "\033[1mInstalled:\033[0m    %s\n" "$INSTALL_DATE"
  printf "\033[1mDirectory:\033[0m    %s\n" "$INSTALL_DIR"
  printf "\033[1mConfig:\033[0m       %s\n" "$CONFIG_FILE"
  printf "\033[1mLogs:\033[0m         %s\n" "$LOG_DIR"
  printf "\n"

  # ── Component table header ──────────────────────────────────
  printf "\033[1m%-16s %-12s %-30s\033[0m\n" "Component" "Status" "Version / Path"
  printf "─────────────── ─────────── ──────────────────────────────\n"

  # ── Git ─────────────────────────────────────────────────────
  local GIT_STATUS="missing"
  local GIT_VERSION="-"
  if has_cmd git; then
    GIT_STATUS="installed"
    GIT_VERSION=$(git --version 2>/dev/null | awk '{print $3}' || echo "unknown")
  fi
  _print_status "Git" "$GIT_STATUS" "$GIT_VERSION"

  # ── Node.js ─────────────────────────────────────────────────
  local NODE_STATUS="missing"
  local NODE_VERSION="-"
  if has_cmd node; then
    NODE_STATUS="installed"
    NODE_VERSION=$(node --version 2>/dev/null || echo "unknown")
    local NODE_MAJOR
    NODE_MAJOR=$(echo "$NODE_VERSION" | tr -d 'v' | cut -d. -f1)
    if [ "${NODE_MAJOR:-0}" -lt 18 ]; then
      NODE_STATUS="old"
      NODE_VERSION="$NODE_VERSION (need >= 18)"
    fi
  fi
  _print_status "Node.js" "$NODE_STATUS" "$NODE_VERSION"

  # ── npm ─────────────────────────────────────────────────────
  local NPM_STATUS="missing"
  local NPM_VERSION="-"
  if has_cmd npm; then
    NPM_STATUS="installed"
    NPM_VERSION=$(npm --version 2>/dev/null || echo "unknown")
  fi
  _print_status "npm" "$NPM_STATUS" "$NPM_VERSION"

  # ── Chromium ────────────────────────────────────────────────
  local CHROMIUM_STATUS="missing"
  local CHROMIUM_PATH="-"
  if [ "${IS_TERMUX:-false}" = true ]; then
    CHROMIUM_STATUS="external"
    CHROMIUM_PATH="(managed externally)"
  else
    for candidate in /usr/bin/chromium /usr/bin/chromium-browser /usr/bin/google-chrome /snap/bin/chromium "$HOME/.cache/ms-playwright"*/chromium-*/chrome-linux/chrome; do
      if [ -x "$candidate" ] 2>/dev/null; then
        CHROMIUM_STATUS="installed"
        CHROMIUM_PATH="$candidate"
        break
      fi
    done

    if [ "$CHROMIUM_STATUS" = "missing" ]; then
      local PW_BROWSERS
      PW_BROWSERS=$(find "$INSTALL_DIR/node_modules" -path "*/chromium*/chrome-linux/chrome" 2>/dev/null | head -1 || true)
      if [ -n "$PW_BROWSERS" ]; then
        CHROMIUM_STATUS="installed"
        CHROMIUM_PATH="$PW_BROWSERS"
      fi
    fi
  fi
  _print_status "Chromium" "$CHROMIUM_STATUS" "$CHROMIUM_PATH"

  # ── Xvfb ────────────────────────────────────────────────────
  if [ "${IS_TERMUX:-false}" != true ]; then
    local XVFB_STATUS="missing"
    local XVFB_VERSION="-"
    if has_cmd Xvfb || has_cmd xvfb-run; then
      XVFB_STATUS="installed"
      XVFB_VERSION=$(Xvfb -version 2>/dev/null | head -1 | awk '{print $NF}' || echo "present")
    fi
    _print_status "Xvfb" "$XVFB_STATUS" "$XVFB_VERSION"
  fi

  # ── x11vnc ──────────────────────────────────────────────────
  if [ "${IS_TERMUX:-false}" != true ]; then
    local VNC_STATUS="missing"
    local VNC_VERSION="-"
    if has_cmd x11vnc; then
      VNC_STATUS="installed"
      VNC_VERSION=$(x11vnc --version 2>/dev/null | head -1 | awk '{print $NF}' || echo "present")
    fi
    _print_status "x11vnc" "$VNC_STATUS" "$VNC_VERSION"
  fi

  # ── Project files ───────────────────────────────────────────
  local PROJECT_STATUS="missing"
  local PROJECT_DETAIL="-"
  local REQUIRED_FILES=(automation.js config.js proxy-rotator.js profile-generator.js vplink3.0.sh vplink-desktop.sh install.sh package.json)
  local FILES_FOUND=0
  for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$INSTALL_DIR/$f" ]; then
      FILES_FOUND=$((FILES_FOUND + 1))
    fi
  done
  if [ "$FILES_FOUND" -eq ${#REQUIRED_FILES[@]} ]; then
    PROJECT_STATUS="complete"
    PROJECT_DETAIL="$FILES_FOUND/${#REQUIRED_FILES[@]} files"
  elif [ "$FILES_FOUND" -gt 0 ]; then
    PROJECT_STATUS="partial"
    PROJECT_DETAIL="$FILES_FOUND/${#REQUIRED_FILES[@]} files"
  fi
  _print_status "Project files" "$PROJECT_STATUS" "$PROJECT_DETAIL"

  # ── node_modules ────────────────────────────────────────────
  local NODEMOD_STATUS="missing"
  local NODEMOD_DETAIL="-"
  if [ -d "$INSTALL_DIR/node_modules" ]; then
    local PKG_COUNT
    PKG_COUNT=$(find "$INSTALL_DIR/node_modules" -maxdepth 1 -type d 2>/dev/null | wc -l)
    NODEMOD_STATUS="installed"
    NODEMOD_DETAIL="$PKG_COUNT packages"
  fi
  _print_status "node_modules" "$NODEMOD_STATUS" "$NODEMOD_DETAIL"

  # ── Global command ──────────────────────────────────────────
  local GLOB_STATUS="missing"
  local GLOB_PATH="-"
  for candidate in "$HOME/.local/bin/vplink3.0" /usr/local/bin/vplink3.0 /usr/bin/vplink3.0; do
    if [ -x "$candidate" ]; then
      GLOB_STATUS="installed"
      GLOB_PATH="$candidate"
      break
    fi
  done
  _print_status "Global command" "$GLOB_STATUS" "$GLOB_PATH"

  # ── Config file ─────────────────────────────────────────────
  local CFG_STATUS="missing"
  local CFG_DETAIL="-"
  if [ -f "$CONFIG_FILE" ]; then
    CFG_STATUS="exists"
    local CFG_SIZE
    CFG_SIZE=$(wc -c < "$CONFIG_FILE" 2>/dev/null || echo "?")
    CFG_DETAIL="$CONFIG_FILE ($CFG_SIZE bytes)"
  fi
  _print_status "Config file" "$CFG_STATUS" "$CFG_DETAIL"

  printf "\n"

  # ── Disk usage ──────────────────────────────────────────────
  printf "\033[1mDisk Usage:\033[0m\n"
  if [ -d "$INSTALL_DIR" ]; then
    local DISK_USAGE
    DISK_USAGE=$(du -sh "$INSTALL_DIR" 2>/dev/null | awk '{print $1}' || echo "unknown")
    printf "  Project:       %s\n" "$DISK_USAGE"
  else
    printf "  Project:       not installed\n"
  fi

  if [ -d "$CONFIG_DIR" ]; then
    local CFG_DISK
    CFG_DISK=$(du -sh "$CONFIG_DIR" 2>/dev/null | awk '{print $1}' || echo "unknown")
    printf "  Config:        %s\n" "$CFG_DISK"
  else
    printf "  Config:        not present\n"
  fi

  if [ -d "$INSTALL_DIR/node_modules" ]; then
    local NM_DISK
    NM_DISK=$(du -sh "$INSTALL_DIR/node_modules" 2>/dev/null | awk '{print $1}' || echo "unknown")
    printf "  node_modules:  %s\n" "$NM_DISK"
  fi

  local HOME_AVAIL
  HOME_AVAIL=$(df -h "$HOME" 2>/dev/null | awk 'NR==2{print $4}' || echo "unknown")
  printf "  Free space:    %s\n" "$HOME_AVAIL"

  printf "\n"
  return 0
}

_print_status() {
  local NAME="$1"
  local STATUS="$2"
  local DETAIL="$3"

  local COLOR SYMBOL
  case "$STATUS" in
    installed|complete|exists)
      COLOR="\033[0;32m"
      SYMBOL="✓"
      ;;
    old|partial)
      COLOR="\033[1;33m"
      SYMBOL="⚠"
      ;;
    external)
      COLOR="\033[0;36m"
      SYMBOL="○"
      ;;
    *)
      COLOR="\033[0;31m"
      SYMBOL="✗"
      ;;
  esac

  printf "%-16s ${COLOR}%-12s${NC} %-30s\n" "$NAME" " $SYMBOL $STATUS" "$DETAIL"
}
