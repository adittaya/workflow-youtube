#!/bin/bash
# VPLink 3.0 — Virtual Desktop Manager
# Manages Xvfb virtual framebuffer + x11vnc for headed Chrome on headless servers
#
# Usage:
#   vplink-desktop start   [--vnc] [--port N] [--display :NN] [--password FILE] [--resolution WxHxD]
#   vplink-desktop stop    [--display :NN]
#   vplink-desktop status
#   vplink-desktop password [--set] [--file PATH]

CONFIG_DIR="$HOME/.vplink3.0"
CONFIG_FILE="$CONFIG_DIR/config.json"
DISPLAY=""
XVFB_PID=""
VNC_PID=""
RESOLUTION="1280x720x24"
VNC_PORT="5900"
VNC_PASSWD_FILE="$CONFIG_DIR/vnc.passwd"
TIMESTAMP=""

# ── Colors ──
# shellcheck disable=SC2034
BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "  ${CYAN}${1}${NC}"; }
ok()    { echo -e "  ${GREEN}✓${NC} ${1}"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} ${1}"; }
fail()  { echo -e "  ${RED}✗${NC} ${1}"; }

# ── Help ──
usage() {
  echo "VPLink 3.0 — Virtual Desktop Manager"
  echo ""
  echo "Usage:"
  echo "  $0 start   [options]    Start Xvfb (+ optional x11vnc)"
  echo "  $0 stop    [options]    Stop Xvfb + x11vnc"
  echo "  $0 status               Show virtual desktop status"
  echo "  $0 password [options]    Set VNC password"
  echo ""
  echo "Options (start):"
  echo "  --display :NN       Display number (default: auto)"
  echo "  --resolution WxHxD  Resolution (default: 1280x720x24)"
  echo "  --vnc               Enable x11vnc"
  echo "  --port N            VNC port (default: 5900)"
  echo "  --password FILE     VNC password file (default: ~/.vplink3.0/vnc.passwd)"
  echo ""
  echo "Options (stop):"
  echo "  --display :NN       Display number to stop (default: auto)"
  echo ""
  echo "Options (password):"
  echo "  --set               Set new password (interactive)"
  echo "  --file PATH         Password file path"
  echo ""
  echo "Examples:"
  echo "  $0 start --vnc                      # Xvfb + VNC on auto display"
  echo "  $0 start --vnc --display :42        # Specific display"
  echo "  $0 start --vnc --port 5901          # Custom VNC port"
  echo "  $0 stop                             # Stop all VPLink displays"
  echo "  $0 stop --display :42               # Stop specific display"
  echo "  $0 password --set                   # Set VNC password"
}

# ── Find available display ──
find_display() {
  for d in $(seq 99 108); do
    if [ ! -e "/tmp/.X11-unix/X$d" ]; then
      echo ":$d"
      return 0
    fi
  done
  # If all taken, try 109-199
  for d in $(seq 109 199); do
    if [ ! -e "/tmp/.X11-unix/X$d" ]; then
      echo ":$d"
      return 0
    fi
  done
  echo ""
  return 1
}

# ── Parse config ──
cfg_get() {
  local key="$1"
  if [ -f "$CONFIG_FILE" ]; then
    node -e "
      try {
        const c = JSON.parse(require('fs').readFileSync('$CONFIG_FILE','utf8'));
        console.log(c['$key'] !== undefined ? c['$key'] : '');
      } catch(e) { console.log(''); }
    " 2>/dev/null
  fi
}

# ── Check dependencies ──
check_deps() {
  local missing=0
  if ! command -v Xvfb &>/dev/null; then
    fail "Xvfb not found. Install xvfb package."
    missing=1
  fi
  if ! command -v xdpyinfo &>/dev/null; then
    warn "xdpyinfo not found — display validation will be skipped. Install x11-utils."
  fi
  return $missing
}

# ── Check if display is alive ──
display_alive() {
  local dpy="$1"
  if command -v xdpyinfo &>/dev/null; then
    DISPLAY="$dpy" xdpyinfo &>/dev/null
    return $?
  fi
  # Fallback: check lock file
  local disp_num="${dpy#:}"
  [ -e "/tmp/.X11-unix/X$disp_num" ]
  return $?
}

# ── Save PID and display info ──
save_state() {
  local disp="$1" xvfb_pid="$2" vnc_pid="$3" vnc_port="$4"
  mkdir -p "$CONFIG_DIR"
  TIMESTAMP=$(date +%s)
  cat > "$CONFIG_DIR/desktop_state.json" <<EOF
{
  "display": "$disp",
  "xvfb_pid": $xvfb_pid,
  "vnc_pid": ${vnc_pid:-0},
  "vnc_port": ${vnc_port:-0},
  "timestamp": $TIMESTAMP,
  "resolution": "$RESOLUTION"
}
EOF
}

# ── Load saved state ──
load_state() {
  local state_file="$CONFIG_DIR/desktop_state.json"
  if [ -f "$state_file" ]; then
    DISPLAY=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$state_file','utf8')).display||'')}catch(e){}" 2>/dev/null)
    XVFB_PID=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$state_file','utf8')).xvfb_pid||0)}catch(e){}" 2>/dev/null)
    VNC_PID=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$state_file','utf8')).vnc_pid||0)}catch(e){}" 2>/dev/null)
    VNC_PORT=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$state_file','utf8')).vnc_port||5900)}catch(e){}" 2>/dev/null)
    return 0
  fi
  return 1
}

# ── Start ──
do_start() {
  local use_vnc=0
  local req_display=""

  # Parse args
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --vnc) use_vnc=1 ;;
      --display) req_display="$2"; shift ;;
      --port) VNC_PORT="$2"; shift ;;
      --password) VNC_PASSWD_FILE="$2"; shift ;;
      --resolution) RESOLUTION="$2"; shift ;;
      *) warn "Unknown option: $1" ;;
    esac
    shift
  done

  # Already running?
  load_state
  if [ -n "$DISPLAY" ] && display_alive "$DISPLAY"; then
    warn "Virtual desktop already running on $DISPLAY (PID $XVFB_PID)"
    echo "$DISPLAY"
    return 0
  fi

  check_deps || return 1

  # Determine display
  if [ -n "$req_display" ]; then
    DISPLAY="$req_display"
  else
    DISPLAY=$(find_display)
  fi

  if [ -z "$DISPLAY" ]; then
    fail "No available display number found (99-199 all in use)"
    return 1
  fi

  local disp_num="${DISPLAY#:}"

  # Clean stale lock if present but Xvfb not alive
  if [ -e "/tmp/.X11-unix/X$disp_num" ]; then
    warn "Stale lock found for $DISPLAY, removing..."
    rm -f "/tmp/.X$disp_num-lock" "/tmp/.X11-unix/X$disp_num" 2>/dev/null
  fi

  # Start Xvfb
  info "Starting Xvfb on $DISPLAY (${RESOLUTION})..."
  export LIBGL_ALWAYS_SOFTWARE=1
  Xvfb "$DISPLAY" -screen 0 "$RESOLUTION" -nolisten tcp &
  XVFB_PID=$!
  sleep 1.5

  # Validate
  local validated=0
  if command -v xdpyinfo &>/dev/null; then
    for _unused in 1 2 3; do
      if DISPLAY="$DISPLAY" xdpyinfo &>/dev/null; then
        validated=1
        break
      fi
      sleep 1
    done
  else
    # No xdpyinfo — check process + socket
    if kill -0 "$XVFB_PID" 2>/dev/null && [ -e "/tmp/.X11-unix/X$disp_num" ]; then
      validated=1
    fi
  fi

  if [ "$validated" -ne 1 ]; then
    fail "Xvfb failed to start on $DISPLAY"
    kill "$XVFB_PID" 2>/dev/null || true
    rm -f "/tmp/.X$disp_num-lock" "/tmp/.X11-unix/X$disp_num" 2>/dev/null
    return 1
  fi

  ok "Xvfb running on $DISPLAY (PID $XVFB_PID)"

  # Start x11vnc
  local vnc_pid=""
  if [ "$use_vnc" -eq 1 ]; then
    local vnc_args=(-display "$DISPLAY" -forever -shared -rfbport "$VNC_PORT")
    # Use password file if it exists
    if [ -f "$VNC_PASSWD_FILE" ]; then
      vnc_args+=(-rfbauth "$VNC_PASSWD_FILE")
      ok "VNC auth enabled ($VNC_PASSWD_FILE)"
    else
      warn "No VNC password file — VNC will be UNPROTECTED"
      warn "Set a password: vplink-desktop password --set"
    fi

    # Kill any existing x11vnc on this display
    pkill -f "x11vnc.*$DISPLAY" 2>/dev/null || true
    sleep 0.5

    x11vnc "${vnc_args[@]}" &
    vnc_pid=$!
    sleep 1

    if kill -0 "$vnc_pid" 2>/dev/null; then
      ok "x11vnc running on port $VNC_PORT (PID $vnc_pid)"
    else
      warn "x11vnc failed to start"
      vnc_pid=""
    fi
  fi

  # Save state
  save_state "$DISPLAY" "$XVFB_PID" "$vnc_pid" "$VNC_PORT"
  export DISPLAY="$DISPLAY"

  echo "$DISPLAY"
  return 0
}

# ── Stop ──
do_stop() {
  local req_display=""

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --display) req_display="$2"; shift ;;
      *) warn "Unknown option: $1" ;;
    esac
    shift
  done

  # If specific display requested
  if [ -n "$req_display" ]; then
    local disp_num="${req_display#:}"
    info "Stopping processes on $req_display..."

    pkill -x x11vnc 2>/dev/null || true
    pkill -x "Xvfb" 2>/dev/null || true
    sleep 0.5

    rm -f "/tmp/.X$disp_num-lock" "/tmp/.X11-unix/X$disp_num" 2>/dev/null

    # If this was the saved display, clear state
    local saved_disp
    saved_disp=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$CONFIG_DIR/desktop_state.json','utf8')).display||'')}catch(e){}" 2>/dev/null)
    if [ "$req_display" = "$saved_disp" ]; then
      rm -f "$CONFIG_DIR/desktop_state.json" 2>/dev/null
    fi
    ok "Stopped $req_display"
    return 0
  fi

  # Stop all VPLink-managed displays
  if [ -f "$CONFIG_DIR/desktop_state.json" ]; then
    load_state
    if [ -n "$XVFB_PID" ] && [ "$XVFB_PID" -gt 0 ]; then
      [ -n "$VNC_PID" ] && [ "$VNC_PID" -gt 0 ] && kill "$VNC_PID" 2>/dev/null || true
      kill "$XVFB_PID" 2>/dev/null || true
      sleep 0.5
    fi
  fi

  # Kill any remaining VPLink-related Xvfb/x11vnc
  if command -v pgrep &>/dev/null; then
    pkill -x x11vnc 2>/dev/null || true
    pkill -x "Xvfb" 2>/dev/null || true
    sleep 0.5
  fi

  # Clean all VPLink-range lock files (99-199)
  for d in $(seq 99 199); do
    rm -f "/tmp/.X$d-lock" "/tmp/.X11-unix/X$d" 2>/dev/null
  done

  rm -f "$CONFIG_DIR/desktop_state.json" 2>/dev/null
  ok "All virtual displays stopped"
}

# ── Status ──
do_status() {
  echo "╔══════════════════════════════════════════════╗"
  echo "║        VPLink Virtual Desktop Status         ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""

  local any_running=0

  # Check saved state
  if [ -f "$CONFIG_DIR/desktop_state.json" ]; then
    load_state
    if [ -n "$DISPLAY" ]; then
      local alive=0
      display_alive "$DISPLAY" && alive=1

      if [ "$alive" -eq 1 ]; then
        ok "Display $DISPLAY — running (XVFB PID $XVFB_PID)"
        any_running=1
        if [ -n "$VNC_PID" ] && [ "$VNC_PID" -gt 0 ] && kill -0 "$VNC_PID" 2>/dev/null; then
          ok "  VNC on port $VNC_PORT (PID $VNC_PID)"
        fi
        echo "  Resolution: $RESOLUTION"
        echo "  Since: $(date -d "@$TIMESTAMP" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'unknown')"
      else
        warn "Display $DISPLAY — saved state but NOT RUNNING (stale PID $XVFB_PID)"
        fail "  Xvfb process dead. Clean with: vplink-desktop stop"
      fi
    fi
  else
    warn "No saved virtual desktop state"
  fi

  # Scan for orphan Xvfb processes
  local orphan_xvfb
  orphan_xvfb=$(pgrep -a Xvfb 2>/dev/null | grep -E ':99|:10[0-8]' || true)
  if [ -n "$orphan_xvfb" ]; then
    echo ""
    info "Orphan Xvfb processes:"
    echo "$orphan_xvfb" | while IFS= read -r line; do
      echo "  $line"
    done
  fi

  # Scan for x11vnc
  local orphan_vnc
  orphan_vnc=$(pgrep -a x11vnc 2>/dev/null || true)
  if [ -n "$orphan_vnc" ]; then
    echo ""
    info "x11vnc processes:"
    echo "$orphan_vnc" | while IFS= read -r line; do
      echo "  $line"
    done
  fi

  # VNC password status
  echo ""
  if [ -f "$VNC_PASSWD_FILE" ]; then
    ok "VNC password set"
  else
    warn "VNC password NOT set (use 'vplink-desktop password --set')"
  fi

  # DISPLAY variable
  echo ""
  if [ -n "$DISPLAY" ]; then
    info "Current DISPLAY: $DISPLAY"
  fi

  echo ""
  if [ "$any_running" -eq 1 ]; then
    ok "Virtual desktop: ACTIVE"
  else
    warn "Virtual desktop: INACTIVE"
    echo ""
    info "Start with: vplink-desktop start --vnc"
  fi
}

# ── Password ──
do_password() {
  local set_mode=0
  local passwd_file="$VNC_PASSWD_FILE"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --set) set_mode=1 ;;
      --file) passwd_file="$2"; shift ;;
      *) warn "Unknown option: $1" ;;
    esac
    shift
  done

  if [ "$set_mode" -eq 1 ]; then
    if ! command -v x11vnc &>/dev/null; then
      fail "x11vnc not installed — cannot set password"
      return 1
    fi

    mkdir -p "$(dirname "$passwd_file")"
    echo "  Enter VNC password (will be stored encrypted):"
    x11vnc -storepasswd "$passwd_file" 2>/dev/null || {
      # Fallback: use -passwd if -storepasswd fails
      read -s -p "  Password: " VNC_PASS
      echo ""
      if [ -z "$VNC_PASS" ]; then
        fail "Password cannot be empty"
        return 1
      fi
      # Generate password file using x11vnc
      echo "$VNC_PASS" | x11vnc -storepasswd - "$passwd_file" 2>/dev/null || {
        # Create a simple passwd file (less secure but works)
        printf "%s\n%s\n" "$VNC_PASS" "$VNC_PASS" | x11vnc -storepasswd - "$passwd_file" 2>/dev/null || {
          fail "Failed to create VNC password file"
          return 1
        }
      }
    }
    chmod 600 "$passwd_file"
    ok "VNC password saved to $passwd_file"
  else
    if [ -f "$passwd_file" ]; then
      ok "VNC password file exists: $passwd_file"
      ls -la "$passwd_file"
    else
      fail "No VNC password file at $passwd_file"
      echo "  Set one: vplink-desktop password --set"
    fi
  fi
}

# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

mkdir -p "$CONFIG_DIR"

case "${1:-}" in
  start)
    shift
    do_start "$@"
    ;;
  stop)
    shift
    do_stop "$@"
    ;;
  status)
    do_status
    ;;
  password)
    shift
    do_password "$@"
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    if [ -n "$1" ] && [ "${1:0:1}" != "-" ]; then
      fail "Unknown command: $1"
    fi
    usage
    ;;
esac
