#!/usr/bin/env bash
# installer/verification/doctor.sh — System diagnostics command
# Comprehensive system check for VPLink 3.0.
# Usage: cmd_doctor

cmd_doctor() {
  set -euo pipefail

  local ISSUES=0
  local TOTAL_CHECKS=0
  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"
  local CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/.vplink3.0"
  [ -d "$HOME/.vplink3.0" ] && CONFIG_DIR="$HOME/.vplink3.0"
  local CONFIG_FILE="$CONFIG_DIR/config.json"

  printf "\n\033[1mVPLink Doctor v3.0.0\033[0m\n\n"

  # ── System ──────────────────────────────────────────────────
  printf "\033[1mSystem:\033[0m\n"

  # OS detection
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local OS_NAME="unknown"
  if [ -f /etc/os-release ]; then
    OS_NAME=$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo "unknown")
  elif has_cmd uname; then
    OS_NAME=$(uname -s -r 2>/dev/null || echo "unknown")
  fi
  _doctor_check "OS" "$OS_NAME" true

  # Architecture
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local SYS_ARCH
  SYS_ARCH=$(uname -m 2>/dev/null || echo "unknown")
  _doctor_check "Arch" "$SYS_ARCH" true

  # Package manager
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local PKG_MGR="none"
  for candidate in apt-get dnf yum pacman apk brew pkg; do
    if has_cmd "$candidate"; then
      PKG_MGR="$candidate"
      break
    fi
  done
  _doctor_check "Package manager" "$PKG_MGR" "$([ "$PKG_MGR" != "none" ])"

  # Disk space
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local DISK_AVAIL
  DISK_AVAIL=$(df -h "$HOME" 2>/dev/null | awk 'NR==2{print $4}' || echo "unknown")
  local DISK_OK=true
  if [ "$DISK_AVAIL" != "unknown" ]; then
    local DISK_NUM
    DISK_NUM=$(echo "$DISK_AVAIL" | tr -d 'GgMm' | awk '{print $1}' || echo "0")
    case "$DISK_AVAIL" in
      *G*) DISK_NUM="${DISK_NUM%%.*}" ;;
      *M*)
        DISK_NUM=$(echo "$DISK_AVAIL" | tr -d 'Mm')
        if [ "${DISK_NUM%%.*}" -lt 500 ] 2>/dev/null; then
          DISK_OK=false
        fi
        ;;
    esac
  fi
  _doctor_check "Disk space" "${DISK_AVAIL} available" "$DISK_OK"

  printf "\n"

  # ── Tools ───────────────────────────────────────────────────
  printf "\033[1mTools:\033[0m\n"

  # git
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if has_cmd git; then
    _doctor_check "git" "$(git --version 2>/dev/null | awk '{print $3}')" true
  else
    _doctor_check "git" "NOT FOUND — install with: sudo apt-get install git" false
    ISSUES=$((ISSUES + 1))
  fi

  # node
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if has_cmd node; then
    local NODE_VER
    NODE_VER=$(node --version 2>/dev/null | tr -d 'v' || echo "unknown")
    local NODE_MAJOR
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "${NODE_MAJOR:-0}" -ge 18 ]; then
      _doctor_check "node" "$NODE_VER" true
    else
      _doctor_check "node" "$NODE_VER (need >= 18 — install from https://nodejs.org)" false
      ISSUES=$((ISSUES + 1))
    fi
  else
    _doctor_check "node" "NOT FOUND — install Node.js >= 18 from https://nodejs.org" false
    ISSUES=$((ISSUES + 1))
  fi

  # npm
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if has_cmd npm; then
    _doctor_check "npm" "$(npm --version 2>/dev/null)" true
  else
    _doctor_check "npm" "NOT FOUND — comes with Node.js" false
    ISSUES=$((ISSUES + 1))
  fi

  # curl
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if has_cmd curl; then
    _doctor_check "curl" "$(curl --version 2>/dev/null | head -1 | awk '{print $2}')" true
  else
    _doctor_check "curl" "NOT FOUND — install with: sudo apt-get install curl" false
    ISSUES=$((ISSUES + 1))
  fi

  printf "\n"

  # ── Network ─────────────────────────────────────────────────
  printf "\033[1mNetwork:\033[0m\n"

  # Internet connectivity
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local NET_OK=false
  if has_cmd curl; then
    curl -sSf --max-time 10 --connect-timeout 5 "https://www.google.com" >/dev/null 2>&1 && NET_OK=true
  elif has_cmd wget; then
    wget -q --timeout=10 --spider "https://www.google.com" 2>/dev/null && NET_OK=true
  fi
  if [ "$NET_OK" = true ]; then
    _doctor_check "Internet" "connected" true
  else
    _doctor_check "Internet" "NOT CONNECTED — check your network" false
    ISSUES=$((ISSUES + 1))
  fi

  # GitHub connectivity
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local GH_OK=false
  if has_cmd curl; then
    curl -sSf --max-time 10 --connect-timeout 5 "https://github.com" >/dev/null 2>&1 && GH_OK=true
  elif has_cmd git; then
    git ls-remote --exit-code "https://github.com/adittaya/VPLINK-3.0.git" HEAD >/dev/null 2>&1 && GH_OK=true
  fi
  if [ "$GH_OK" = true ]; then
    _doctor_check "GitHub" "reachable" true
  else
    _doctor_check "GitHub" "UNREACHABLE — may need VPN or proxy" false
    ISSUES=$((ISSUES + 1))
  fi

  # npm registry
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local NPM_OK=false
  if has_cmd npm; then
    npm ping --registry https://registry.npmjs.org/ >/dev/null 2>&1 && NPM_OK=true
  elif has_cmd curl; then
    curl -sSf --max-time 10 --connect-timeout 5 "https://registry.npmjs.org/playwright" >/dev/null 2>&1 && NPM_OK=true
  fi
  if [ "$NPM_OK" = true ]; then
    _doctor_check "npm registry" "reachable" true
  else
    _doctor_check "npm registry" "UNREACHABLE — npm install may fail" false
    ISSUES=$((ISSUES + 1))
  fi

  printf "\n"

  # ── Project ─────────────────────────────────────────────────
  printf "\033[1mProject:\033[0m\n"

  # Project directory
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if [ -d "$INSTALL_DIR/.git" ]; then
    local PROJ_SIZE
    PROJ_SIZE=$(du -sh "$INSTALL_DIR" 2>/dev/null | awk '{print $1}' || echo "?")
    _doctor_check "Project directory" "$INSTALL_DIR ($PROJ_SIZE)" true
  elif [ -d "$INSTALL_DIR" ]; then
    _doctor_check "Project directory" "$INSTALL_DIR (not a git repo)" false
    ISSUES=$((ISSUES + 1))
  else
    _doctor_check "Project directory" "$INSTALL_DIR (not found)" false
    ISSUES=$((ISSUES + 1))
  fi

  # node_modules
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if [ -d "$INSTALL_DIR/node_modules" ]; then
    local PKG_COUNT
    PKG_COUNT=$(find "$INSTALL_DIR/node_modules" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    _doctor_check "node_modules" "$PKG_COUNT packages" true
  else
    _doctor_check "node_modules" "NOT INSTALLED — run: cd $INSTALL_DIR && npm install" false
    ISSUES=$((ISSUES + 1))
  fi

  # Config
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  if [ -f "$CONFIG_FILE" ]; then
    _doctor_check "Config" "$CONFIG_FILE" true
  else
    _doctor_check "Config" "not found (will be created on first use)" true
  fi

  # Port availability
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local PORT_5900_FREE=true
  if has_cmd ss; then
    if ss -tlnp 2>/dev/null | grep -q ":5900 " 2>/dev/null; then
      PORT_5900_FREE=false
    fi
  elif has_cmd netstat; then
    if netstat -tlnp 2>/dev/null | grep -q ":5900 " 2>/dev/null; then
      PORT_5900_FREE=false
    fi
  elif has_cmd lsof; then
    if lsof -i :5900 >/dev/null 2>&1; then
      PORT_5900_FREE=false
    fi
  fi
  if [ "$PORT_5900_FREE" = true ]; then
    _doctor_check "Port 5900 (VNC)" "available" true
  else
    _doctor_check "Port 5900 (VNC)" "IN USE — VNC may not start" false
    ISSUES=$((ISSUES + 1))
  fi

  # Shell profile writability
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  local PROFILE_WRITABLE=false
  for PROFILE in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    if [ -f "$PROFILE" ] && [ -w "$PROFILE" ]; then
      PROFILE_WRITABLE=true
      break
    fi
  done
  if [ "$PROFILE_WRITABLE" = true ]; then
    _doctor_check "Shell profile" "writable" true
  else
    _doctor_check "Shell profile" "not writable (PATH updates may fail)" false
    ISSUES=$((ISSUES + 1))
  fi

  printf "\n"

  # ── Summary ─────────────────────────────────────────────────
  if [ "$ISSUES" -eq 0 ]; then
    printf "\033[0;32mIssues found: 0\033[0m — System is ready for VPLink 3.0!\n\n"
  else
    printf "\033[0;31mIssues found: %d\033[0m\n\n" "$ISSUES"
    printf "Suggestions:\n"
    if [ "${ISSUES:-0}" -gt 0 ]; then
      printf "  • Run 'vplink3.0 repair' to auto-fix common issues\n"
      printf "  • Run 'vplink3.0 install --skip-deps' to reinstall without system packages\n"
      printf "  • Check https://github.com/adittaya/VPLINK-3.0 for documentation\n"
    fi
    printf "\n"
  fi

  return "$ISSUES"
}

_doctor_check() {
  local NAME="$1"
  local DETAIL="$2"
  local PASSED="$3"

  local COLOR SYMBOL NC="\033[0m"
  if [ "$PASSED" = true ]; then
    COLOR="\033[0;32m"
    SYMBOL="✓"
  else
    COLOR="\033[0;31m"
    SYMBOL="✗"
  fi

  printf "  ${COLOR}%s${NC} %-18s %s\n" "$SYMBOL" "$NAME:" "$DETAIL"
}
