#!/bin/bash

SCRIPT="$(readlink -f "$0")"  # resolve symlinks to real path
SCRIPT_DIR="$(dirname "$SCRIPT")"
AUTOMATION="$SCRIPT_DIR/automation.js"
CONFIG_MODULE="$SCRIPT_DIR/config.js"
PROXY_ROTATOR="$SCRIPT_DIR/proxy-rotator.js"
PROFILE_GENERATOR="$SCRIPT_DIR/profile-generator.js"
INSTALLER="$SCRIPT_DIR/install.sh"

NODE_BIN="node"
[ -n "${PREFIX:-}" ] && [ -x "$PREFIX/bin/node" ] && NODE_BIN="$PREFIX/bin/node"

# ── Dispatch commands ─────────────────────────────────
case "${1:-}" in
  update|self-update)
    exec bash "$INSTALLER" update
    ;;
  uninstall)
    exec bash "$INSTALLER" uninstall --all
    ;;
  config)
    shift
    exec node "$CONFIG_MODULE" "$@"
    ;;
esac

# ── Color helpers ──────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

info()  { echo -e "  ${CYAN}${1}${NC}"; }
ok()    { echo -e "  ${GREEN}✓${NC} ${1}"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} ${1}"; }
fail()  { echo -e "  ${RED}✗${NC} ${1}"; }

# ── Deep cleanup ──────────────────────────────────────
deep_cleanup() {
  local cleaned=0
  # Remove per-view destination files
  for f in "$SCRIPT_DIR"/destination_url_*.txt; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Remove main destination file
  [ -f "$SCRIPT_DIR/destination_url.txt" ] && rm -f "$SCRIPT_DIR/destination_url.txt" && cleaned=$((cleaned + 1))
  # Remove debug screenshots and HTML captures
  for f in "$SCRIPT_DIR"/debug_*.png "$SCRIPT_DIR"/debug_*.html; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Remove event and summary files
  for f in "$SCRIPT_DIR"/events*.json "$SCRIPT_DIR"/summary.json; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Remove screen recordings
  for f in "$SCRIPT_DIR"/*.mp4 "$SCRIPT_DIR"/*.webm "$SCRIPT_DIR"/screen_recording* "$SCRIPT_DIR"/recording_*; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Remove old record artifacts
  for f in "$SCRIPT_DIR"/record.js "$SCRIPT_DIR"/record.sh; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Clean screenshots directory
  [ -d "$SCRIPT_DIR/screenshots" ] && rm -rf "$SCRIPT_DIR/screenshots" && cleaned=$((cleaned + 1))
  # Remove stale Xvfb lock files
  rm -f /tmp/.X*-lock /tmp/.X11-unix/X* 2>/dev/null
  # Remove Chromium crashpad / session tmp dirs
  rm -rf /tmp/.org.chromium.* /tmp/.com.google.Chrome.* 2>/dev/null
  # Remove old Playwright browser artifacts in /tmp
  rm -rf /tmp/playwright-* /tmp/pp* 2>/dev/null
  if [ "$cleaned" -gt 0 ]; then
    ok "cleaned up $cleaned old artifacts"
  fi
}

# ── Detect Termux ─────────────────────────────────────
is_termux() {
  [ -n "$PREFIX" ] && [ -d /data/data/com.termux ] 2>/dev/null
}

if is_termux; then
  TERMUX=1
else
  TERMUX=0
fi

# ── Config helpers ─────────────────────────────────────
cfg_get() { $NODE_BIN "$CONFIG_MODULE" --get "$1" 2>/dev/null; }
cfg_set() { $NODE_BIN "$CONFIG_MODULE" --set "$1" "$2" 2>/dev/null; }

# ── PID tracking ───────────────────────────────────────
PIDS=()

track_pid() {
  PIDS+=("$1")
}

cleanup_pids() {
  trap - SIGINT SIGTERM 2>/dev/null
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  PIDS=()
  # Stop virtual desktop via vplink-desktop
  DESKTOP_CMD="$SCRIPT_DIR/vplink-desktop.sh"
  [ ! -x "$DESKTOP_CMD" ] && DESKTOP_CMD="vplink-desktop"
  if command -v "$DESKTOP_CMD" &>/dev/null; then
    "$DESKTOP_CMD" stop 2>/dev/null || true
  else
    # Fallback: kill by exact process name only (no -f to avoid matching ourselves)
    killall Xvfb 2>/dev/null || true
    killall x11vnc 2>/dev/null || true
    [ -n "$DISPLAY" ] && rm -f "/tmp/.X${DISPLAY#:}-lock" "/tmp/.X11-unix/X${DISPLAY#:}" 2>/dev/null
  fi
}

trap 'echo ""; echo "Interrupted."; cleanup_pids; exit 130' SIGINT SIGTERM

# ── VNC detection ──────────────────────────────────────
detect_vnc() {
  local ports
  ports=$(ss -tlnp 2>/dev/null | grep -oE ':[0-9]+ ' | grep -oE '[0-9]+' | grep '^59[0-9][0-9]$' | sort -u || true)
  if [ -z "$ports" ]; then
    echo ""
    return 1
  fi
  echo ""
  info "${GREEN}VNC server(s) detected on port(s):${NC} $(echo "$ports" | tr '\n' ' ')"
  echo ""
}

# ── Load saved config ──────────────────────────────────
SAVED_KEY=$(cfg_get "last_key" 2>/dev/null)
SAVED_VIEWS=$(cfg_get "views" 2>/dev/null)
SAVED_PROXY=$(cfg_get "proxy_enabled" 2>/dev/null)
SAVED_TIER=$(cfg_get "proxy_tier" 2>/dev/null)
SAVED_YT=$(cfg_get "youtube_traffic" 2>/dev/null)
SAVED_MOBILE=$(cfg_get "mobile_profile" 2>/dev/null)
SAVED_VNC_PORT=$(cfg_get "vnc_port" 2>/dev/null)
SAVED_DESKTOP=$(cfg_get "virtual_desktop" 2>/dev/null)

[ -z "$SAVED_VIEWS" ] || [ "$SAVED_VIEWS" = "0" ] && SAVED_VIEWS=1

# ════════════════════════════════════════════════════════
#  QUESTIONS
# ════════════════════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║         VPLink 3.0 — Interactive             ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Link / Key ──────────────────────────────────────
DEFAULT_INPUT=""
[ -n "$SAVED_KEY" ] && DEFAULT_INPUT="$SAVED_KEY"
read -p "Enter vplink URL or key [${DEFAULT_INPUT}]: " INPUT
INPUT="${INPUT:-$DEFAULT_INPUT}"
KEY=$(echo "$INPUT" | sed 's|https\?://vplink.in/||' | xargs)
while [ -z "$KEY" ]; do
  read -p "Key cannot be empty. Enter vplink URL or key: " INPUT
  KEY=$(echo "$INPUT" | sed 's|https\?://vplink.in/||' | xargs)
done
cfg_set "last_key" "$KEY"

# ── 2. Multiple URLs feature ───────────────────────────
MULTI_URLS=""
read -p "Use multiple vplink URLs (random rotation)? (y/N): " MULTI_CHOICE
if [[ "$MULTI_CHOICE" =~ ^[yY] ]]; then
  read -p "Enter all URLs/keys (comma-separated): " MULTI_INPUT
  MULTI_URLS=$(echo "$MULTI_INPUT" | xargs)
  # Save to config
  cfg_set "random_urls" "$MULTI_URLS"
fi

# ── 3. Views ───────────────────────────────────────────
read -p "How many views? (${SAVED_VIEWS}): " VIEWS
VIEWS="${VIEWS:-$SAVED_VIEWS}"
[[ ! "$VIEWS" =~ ^[0-9]+$ ]] && VIEWS=$SAVED_VIEWS
cfg_set "views" "$VIEWS"

# ── 4. Proxy rotation ──────────────────────────────────
PROXY_ENABLED="$SAVED_PROXY"
if [ -z "$PROXY_ENABLED" ] || [ "$PROXY_ENABLED" = "false" ]; then PROXY_ENABLED="n"; else PROXY_ENABLED="y"; fi
read -p "Enable proxy rotation? (y/N) [${PROXY_ENABLED}]: " PROXY_CHOICE
PROXY_CHOICE="${PROXY_CHOICE:-$PROXY_ENABLED}"
if [[ "$PROXY_CHOICE" =~ ^[yY] ]]; then
  PROXY_ENABLED="true"
  read -p "Proxy tier? (normal/premium) [${SAVED_TIER:-premium}]: " PROXY_TIER
  PROXY_TIER="${PROXY_TIER:-${SAVED_TIER:-premium}}"
  cfg_set "proxy_enabled" true
  cfg_set "proxy_tier" "$PROXY_TIER"
else
  PROXY_ENABLED="false"
  cfg_set "proxy_enabled" false
fi

# ── 5. YouTube traffic ─────────────────────────────────
YT_ENABLED="$SAVED_YT"
[ -z "$YT_ENABLED" ] || [ "$YT_ENABLED" = "false" ] && YT_DEFAULT="n" || YT_DEFAULT="y"
read -p "Simulate YouTube traffic source? (y/N) [${YT_DEFAULT}]: " YT_CHOICE
YT_CHOICE="${YT_CHOICE:-$YT_DEFAULT}"
if [[ "$YT_CHOICE" =~ ^[yY] ]]; then
  YT_ENABLED="true"
  cfg_set "youtube_traffic" true
else
  YT_ENABLED="false"
  cfg_set "youtube_traffic" false
fi

# ── 6. Mobile profiles ─────────────────────────────────
MOBILE_ENABLED="$SAVED_MOBILE"
[ -z "$MOBILE_ENABLED" ] || [ "$MOBILE_ENABLED" = "false" ] && MOB_DEFAULT="n" || MOB_DEFAULT="y"
read -p "Use random mobile profile per view? (y/N) [${MOB_DEFAULT}]: " MOB_CHOICE
MOB_CHOICE="${MOB_CHOICE:-$MOB_DEFAULT}"
if [[ "$MOB_CHOICE" =~ ^[yY] ]]; then
  MOBILE_ENABLED="true"
  cfg_set "mobile_profile" true
else
  MOBILE_ENABLED="false"
  cfg_set "mobile_profile" false
fi

# ── 7. Display mode ────────────────────────────────────
DESKTOP_NEEDED="n"
if [ "$TERMUX" = 0 ]; then
  # Check for existing desktop display
  EXISTING_DISPLAY="${DISPLAY:-}"
  [ -z "$EXISTING_DISPLAY" ] && command -v xdpyinfo &>/dev/null && EXISTING_DISPLAY=$(xdpyinfo 2>/dev/null | grep 'name of display' | awk '{print $NF}' || true)

  if [ -n "$EXISTING_DISPLAY" ]; then
    DESKTOP_NEEDED="existing"
    info "Using existing display: $EXISTING_DISPLAY"
  else
    [ "$SAVED_DESKTOP" = "false" ] && DESKTOP_DEFAULT="n" || DESKTOP_DEFAULT="y"
    read -p "Use virtual desktop (Xvfb) for headed Chrome? (y/N) [${DESKTOP_DEFAULT}]: " DESKTOP_CHOICE
    DESKTOP_CHOICE="${DESKTOP_CHOICE:-$DESKTOP_DEFAULT}"
    if [[ "$DESKTOP_CHOICE" =~ ^[yY] ]]; then
      DESKTOP_NEEDED="y"
      cfg_set "virtual_desktop" true
    else
      DESKTOP_NEEDED="n"
      cfg_set "virtual_desktop" false
    fi
  fi
fi

# ── 8. VNC ─────────────────────────────────────────────
VNC_NEEDED="n"
VNC_PORT="${SAVED_VNC_PORT:-5900}"
if [ "$TERMUX" = 0 ] && [ "$DESKTOP_NEEDED" = "y" ]; then
  if detect_vnc; then
    read -p "Use existing VNC? (Y/n): " USE_VNC
    if [[ ! "$USE_VNC" =~ ^[nN] ]]; then
      VNC_NEEDED="y"
      read -p "VNC port? (${VNC_PORT}): " VNC_PORT_IN
      VNC_PORT="${VNC_PORT_IN:-$VNC_PORT}"
    else
      read -p "Start a separate VNC? (y/N): " START_VNC
      [[ "$START_VNC" =~ ^[yY] ]] && VNC_NEEDED="y"
      read -p "VNC port? (${VNC_PORT}): " VNC_PORT_IN
      VNC_PORT="${VNC_PORT_IN:-$VNC_PORT}"
    fi
  else
    read -p "VNC viewer needed? (y/N): " VNC_CHOICE
    if [[ "$VNC_CHOICE" =~ ^[yY] ]]; then
      VNC_NEEDED="y"
      read -p "VNC port? (${VNC_PORT}): " VNC_PORT_IN
      VNC_PORT="${VNC_PORT_IN:-$VNC_PORT}"
    fi
  fi
  cfg_set "vnc_port" "$VNC_PORT"
fi

# ════════════════════════════════════════════════════════
#  SUMMARY + CONFIRM
# ════════════════════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║              Run Summary                     ║"
echo "╠══════════════════════════════════════════════╣"
printf "║  %-13s %s\n" "Views:" "$VIEWS"
printf "║  %-13s %s\n" "Key:" "$KEY"
if [ -n "$MULTI_URLS" ]; then
  MULTI_COUNT=$(echo "$MULTI_URLS" | tr ',' '\n' | wc -l)
  printf "║  %-13s %s\n" "Multi-URL:" "✓ enabled ($MULTI_COUNT keys)"
fi
if [ "$PROXY_ENABLED" = true ]; then
  printf "║  %-13s %s\n" "Proxy:" "✓ enabled (${PROXY_TIER})"
else
  printf "║  %-13s %s\n" "Proxy:" "— disabled"
fi
if [ "$YT_ENABLED" = true ]; then
  printf "║  %-13s %s\n" "YouTube src:" "✓ enabled"
else
  printf "║  %-13s %s\n" "YouTube src:" "— disabled"
fi
if [ "$MOBILE_ENABLED" = true ]; then
  printf "║  %-13s %s\n" "Mobile prof:" "✓ enabled"
else
  printf "║  %-13s %s\n" "Mobile prof:" "— disabled"
fi
if [ "$TERMUX" = 1 ]; then
  printf "║  %-13s %s\n" "Mode:" "Termux (headless)"
elif [ "$DESKTOP_NEEDED" = "existing" ]; then
  printf "║  %-13s %s\n" "Mode:" "✓ Existing display ($DISPLAY)"
elif [ "$DESKTOP_NEEDED" = "n" ]; then
  printf "║  %-13s %s\n" "Mode:" "Headless"
else
  printf "║  %-13s %s\n" "Mode:" "✓ Virtual desktop (Xvfb)"
fi
if [[ "$VNC_NEEDED" =~ ^[yY] ]]; then
  printf "║  %-13s %s\n" "VNC:" "✓ :$VNC_PORT"
else
  printf "║  %-13s %s\n" "VNC:" "— disabled"
fi
echo "╚══════════════════════════════════════════════╝"
echo ""

read -p "Proceed? (Y/n): " CONFIRM
[[ "$CONFIRM" =~ ^[nN] ]] && { echo "Aborted."; exit 0; }
echo ""

# ════════════════════════════════════════════════════════
#  RUN LOOP
# ════════════════════════════════════════════════════════

export NODE_PATH="${NODE_PATH:-}:$SCRIPT_DIR/node_modules"
export VPLINK_TERMUX="$TERMUX"

for (( i=1; i<=VIEWS; i++ )); do
  echo "══════════════════════════════════════════════"
  echo "  View $i of $VIEWS"
  echo "══════════════════════════════════════════════"

  deep_cleanup
  cleanup_pids
  sleep 1

  # ── Pick key (random if multi-URL enabled) ──────────
  CURRENT_KEY="$KEY"
  if [ -n "$MULTI_URLS" ]; then
    IFS=',' read -ra URL_ARR <<< "$MULTI_URLS"
    # Filter out empty entries
    VALID_KEYS=()
    for raw in "${URL_ARR[@]}"; do
      k=$(echo "$raw" | sed 's|https\?://vplink.in/||' | xargs)
      [ -n "$k" ] && VALID_KEYS+=("$k")
    done
    if [ ${#VALID_KEYS[@]} -eq 0 ]; then
      warn "No valid keys in multi-URL list, using primary key"
      CURRENT_KEY="$KEY"
    else
      RAND_IDX=$(( RANDOM % ${#VALID_KEYS[@]} ))
      CURRENT_KEY="${VALID_KEYS[$RAND_IDX]}"
      info "Picked key ${RAND_IDX}: ${CURRENT_KEY}"
    fi
  fi

  # ── Proxy ──────────────────────────────────────────
  if [ "$PROXY_ENABLED" = "true" ]; then
    info "Fetching proxy..."
    cd "$SCRIPT_DIR" || exit 1
    # getProxy() already tests each proxy against vplink.in (5s timeout)
    PROXY_RESULT=$($NODE_BIN "$PROXY_ROTATOR" "$PROXY_TIER")
    if [ -n "$PROXY_RESULT" ]; then
      export VPLINK_PROXY="http://${PROXY_RESULT}"
      ok "Proxy: $VPLINK_PROXY"
    else
      warn "No proxy available, running without proxy"
      unset VPLINK_PROXY
    fi
  else
    unset VPLINK_PROXY
  fi

  # ── Profile (UA + viewport + YouTube headers) ──────
  if [ "$MOBILE_ENABLED" = "true" ] || [ "$YT_ENABLED" = "true" ]; then
    cd "$SCRIPT_DIR" || exit 1
    PROFILE_OUTPUT=$($NODE_BIN "$PROFILE_GENERATOR" \
      "mobile=${MOBILE_ENABLED}" "youtube=${YT_ENABLED}")
    if [ -n "$PROFILE_OUTPUT" ]; then
      PROFILE_UA=$(echo "$PROFILE_OUTPUT" | sed -n '1p')
      PROFILE_VIEWPORT=$(echo "$PROFILE_OUTPUT" | sed -n '2p')
      PROFILE_REFERER=$(echo "$PROFILE_OUTPUT" | sed -n '3p')

      export VPLINK_USER_AGENT="$PROFILE_UA"
      VW=$(echo "$PROFILE_VIEWPORT" | cut -d'x' -f1)
      VH=$(echo "$PROFILE_VIEWPORT" | cut -d'x' -f2)
      [ -n "$VW" ] && export VPLINK_VIEWPORT_WIDTH="$VW"
      [ -n "$VH" ] && export VPLINK_VIEWPORT_HEIGHT="$VH"

      if [ "$YT_ENABLED" = "true" ] && [ -n "$PROFILE_REFERER" ]; then
        info "YouTube referer: $PROFILE_REFERER"
      fi
    fi
  else
    unset VPLINK_USER_AGENT VPLINK_VIEWPORT_WIDTH VPLINK_VIEWPORT_HEIGHT
  fi

  # ── Display / Virtual desktop setup ─────────────────
  if [ "$TERMUX" = 1 ]; then
    unset DISPLAY
    export VPLINK_HEADLESS=1
  elif [ "$DESKTOP_NEEDED" = "existing" ]; then
    export DISPLAY="${DISPLAY:-:0}"
    unset VPLINK_HEADLESS
  elif [ "$DESKTOP_NEEDED" = "n" ]; then
    unset DISPLAY
    export VPLINK_HEADLESS=1
  else
    DESKTOP_CMD="$SCRIPT_DIR/vplink-desktop.sh"
    if [ ! -x "$DESKTOP_CMD" ]; then
      DESKTOP_CMD="vplink-desktop"
    fi

    DESKTOP_ARGS="start"
    if [[ "$VNC_NEEDED" =~ ^[yY] ]]; then
      DESKTOP_ARGS="$DESKTOP_ARGS --vnc --port $VNC_PORT"
    fi

    VPLINK_DISPLAY=$($DESKTOP_CMD $DESKTOP_ARGS 2>&1)
    EXIT_D=$?
    if [ "$EXIT_D" -ne 0 ]; then
      warn "Virtual desktop failed to start, running headless"
      unset DISPLAY
      export VPLINK_HEADLESS=1
    else
      VPLINK_DISPLAY=$(echo "$VPLINK_DISPLAY" | grep '^:' | tail -1)
      if [ -n "$VPLINK_DISPLAY" ]; then
        export DISPLAY="$VPLINK_DISPLAY"
        unset VPLINK_HEADLESS
        ok "Virtual desktop on $DISPLAY"
        [[ "$VNC_NEEDED" =~ ^[yY] ]] && ok "VNC on port $VNC_PORT"
      else
        warn "Could not determine display number"
        unset DISPLAY
        export VPLINK_HEADLESS=1
      fi
    fi
  fi

  # ── Run automation ─────────────────────────────────
  cd "$SCRIPT_DIR" || exit 1
  info "Starting automation (timeout: 480s)..."
  DEBUG_FLAG=""
  [ "${VPLINK_DEBUG:-0}" = "1" ] && DEBUG_FLAG="--vplink-debug"
  timeout 480 "$NODE_BIN" "$AUTOMATION" "$CURRENT_KEY" ${DEBUG_FLAG:+"$DEBUG_FLAG"}
  EXIT_CODE=$?
  if [ "$EXIT_CODE" -eq 124 ]; then
    warn "Automation timed out after 480s"
  elif [ "$EXIT_CODE" -ne 0 ]; then
    warn "Automation exited with code $EXIT_CODE"
  fi

  # ── Save result ────────────────────────────────────
  if [ -f "$SCRIPT_DIR/destination_url.txt" ]; then
    DEST=$(cat "$SCRIPT_DIR/destination_url.txt")
    mv "$SCRIPT_DIR/destination_url.txt" "$SCRIPT_DIR/destination_url_${i}.txt"
    ok "Result $i: $DEST"
  else
    warn "No destination URL captured for view $i"
  fi
  echo ""
done

# ── Final cleanup ─────────────────────────────────────
cleanup_pids
# Clean VPLink virtual desktop
DESKTOP_CMD="$SCRIPT_DIR/vplink-desktop.sh"
[ ! -x "$DESKTOP_CMD" ] && DESKTOP_CMD="vplink-desktop"
$DESKTOP_CMD stop 2>/dev/null || true

# ── Summary ────────────────────────────────────────────
echo "══════════════════════════════════════════════"
echo "  All $VIEWS view(s) completed"
echo "══════════════════════════════════════════════"
RESULTS=()
for (( i=1; i<=VIEWS; i++ )); do
  if [ -f "$SCRIPT_DIR/destination_url_${i}.txt" ]; then
    URL=$(cat "$SCRIPT_DIR/destination_url_${i}.txt")
    echo "  View $i: $URL"
    RESULTS+=("$URL")
  fi
done
UNIQUE=$(printf '%s\n' "${RESULTS[@]}" | sort -u | wc -l)
echo "  ───────────────────────────────────────────"
echo "  Unique destinations: $UNIQUE / ${#RESULTS[@]}"
echo ""
echo "Results saved in $SCRIPT_DIR/destination_url_*.txt"
