#!/bin/bash
# ════════════════════════════════════════════════════════
#  VPLink 3.0 — Interactive CLI
#  Automated vplink.in URL funnel
# ════════════════════════════════════════════════════════
set -u

# ── Paths ──────────────────────────────────────────────
SCRIPT="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT")"
AUTOMATION="$SCRIPT_DIR/automation.js"
CONFIG_MODULE="$SCRIPT_DIR/config.js"
PROXY_ROTATOR="$SCRIPT_DIR/proxy-rotator.js"
PROFILE_GENERATOR="$SCRIPT_DIR/profile-generator.js"
INSTALLER="$SCRIPT_DIR/install.sh"

NODE_BIN="node"
[ -n "${PREFIX:-}" ] && [ -x "${PREFIX:-}/bin/node" ] && NODE_BIN="${PREFIX}/bin/node"

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

# ── Colors ─────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "  ${CYAN}${1}${NC}"; }
ok()    { echo -e "  ${GREEN}\u2713${NC} ${1}"; }
warn()  { echo -e "  ${YELLOW}\u26a0${NC} ${1}"; }
fail()  { echo -e "  ${RED}\u2717${NC} ${1}"; }

# ── Termux detection ───────────────────────────────────
is_termux() {
  [ -n "${PREFIX:-}" ] && [ -d /data/data/com.termux ] 2>/dev/null
}
if is_termux; then TERMUX=1; else TERMUX=0; fi

# ── Config helpers ─────────────────────────────────────
cfg_get() { $NODE_BIN "$CONFIG_MODULE" --get "$1" 2>/dev/null; }
cfg_set() { $NODE_BIN "$CONFIG_MODULE" --set "$1" "$2" 2>/dev/null; }

# ════════════════════════════════════════════════════════
#  PROCESS TRACKING & CLEANUP
# ════════════════════════════════════════════════════════

TRACKED_PIDS=()

track_pid() {
  TRACKED_PIDS+=("$1")
}

kill_tracked() {
  [ ${#TRACKED_PIDS[@]} -eq 0 ] && return
  for pid in "${TRACKED_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  TRACKED_PIDS=()
}

CLEANED_UP=0

full_cleanup() {
  [ "$CLEANED_UP" -eq 1 ] && return
  CLEANED_UP=1
  kill_tracked
}

on_exit() {
  full_cleanup
}

on_signal() {
  echo ""
  echo "Interrupted."
  trap '' EXIT
  kill_tracked
  exec kill -9 $$ 2>/dev/null || exit 130
}

trap 'on_exit' EXIT
trap 'on_signal HUP' SIGHUP
trap 'on_signal INT' SIGINT
trap 'on_signal TERM' SIGTERM

# ════════════════════════════════════════════════════════
#  DEEP CLEANUP — remove artifacts from previous runs
# ════════════════════════════════════════════════════════

deep_cleanup() {
  local cleaned=0
  # Destination files
  for f in "$SCRIPT_DIR"/destination_url_*.txt "$SCRIPT_DIR/destination_url.txt"; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Debug captures
  for f in "$SCRIPT_DIR"/debug_*.png "$SCRIPT_DIR"/debug_*.html; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Event/summary files
  for f in "$SCRIPT_DIR"/events*.json "$SCRIPT_DIR/summary.json"; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Screen recordings
  for f in "$SCRIPT_DIR"/*.mp4 "$SCRIPT_DIR"/*.webm "$SCRIPT_DIR"/screen_recording* "$SCRIPT_DIR"/recording_*; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Legacy recorder files
  for f in "$SCRIPT_DIR"/record.js "$SCRIPT_DIR"/record.sh; do
    [ -f "$f" ] && rm -f "$f" && cleaned=$((cleaned + 1))
  done
  # Screenshots directory
  [ -d "$SCRIPT_DIR/screenshots" ] && rm -rf "$SCRIPT_DIR/screenshots" && cleaned=$((cleaned + 1))
  # Stale X11 lock files (VPLink range 99-199)
  for d in $(seq 99 199); do
    rm -f "/tmp/.X${d}-lock" "/tmp/.X11-unix/X${d}" 2>/dev/null
  done
  # Chromium / Playwright temp
  rm -rf /tmp/.org.chromium.* /tmp/.com.google.Chrome.* 2>/dev/null
  rm -rf /tmp/playwright-* /tmp/pp* 2>/dev/null
  [ "$cleaned" -gt 0 ] && ok "cleaned $cleaned old artifacts"
}

# ════════════════════════════════════════════════════════
#  LOAD SAVED CONFIG
# ════════════════════════════════════════════════════════

SAVED_KEY=$(cfg_get "last_key" 2>/dev/null)
SAVED_VIEWS=$(cfg_get "views" 2>/dev/null)
SAVED_PROXY=$(cfg_get "proxy_enabled" 2>/dev/null)
SAVED_TIER=$(cfg_get "proxy_tier" 2>/dev/null)
SAVED_YT=$(cfg_get "youtube_traffic" 2>/dev/null)
SAVED_MOBILE=$(cfg_get "mobile_profile" 2>/dev/null)

[ -z "$SAVED_VIEWS" ] || [ "$SAVED_VIEWS" = "0" ] && SAVED_VIEWS=1

# ════════════════════════════════════════════════════════
#  INTERACTIVE QUESTIONNAIRE
# ════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         VPLink 3.0 — Interactive             ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Link / Key ──────────────────────────────────────
DEFAULT_INPUT="${SAVED_KEY:-}"
read -p "Enter vplink URL or key [${DEFAULT_INPUT}]: " INPUT
INPUT="${INPUT:-$DEFAULT_INPUT}"
# Strip protocol + domain, trailing slash, query params, fragments
KEY=$(echo "$INPUT" | sed 's|https\?://vplink.in/||' | sed 's|[/?#].*||' | xargs)
while [ -z "$KEY" ]; do
  read -p "Key cannot be empty. Enter vplink URL or key: " INPUT
  KEY=$(echo "$INPUT" | sed 's|https\?://vplink.in/||' | sed 's|[/?#].*||' | xargs)
done
cfg_set "last_key" "$KEY"

# ── 2. Multiple URLs ──────────────────────────────────
MULTI_URLS=""
read -p "Use multiple vplink URLs (random rotation)? (y/N): " MULTI_CHOICE
if [[ "$MULTI_CHOICE" =~ ^[yY] ]]; then
  read -p "Enter all URLs/keys (comma-separated): " MULTI_INPUT
  MULTI_URLS=$(echo "$MULTI_INPUT" | xargs)
  cfg_set "random_urls" "$MULTI_URLS"
fi

# ── 3. Views ───────────────────────────────────────────
read -p "How many views? (${SAVED_VIEWS}): " VIEWS
VIEWS="${VIEWS:-$SAVED_VIEWS}"
[[ ! "$VIEWS" =~ ^[0-9]+$ ]] || [ "$VIEWS" -eq 0 ] && VIEWS=$SAVED_VIEWS
cfg_set "views" "$VIEWS"

# ── 4. Proxy rotation ──────────────────────────────────
PROXY_ENABLED="$SAVED_PROXY"
if [ -z "$PROXY_ENABLED" ] || [ "$PROXY_ENABLED" = "false" ]; then
  PROXY_DEFAULT="n"
else
  PROXY_DEFAULT="y"
fi
read -p "Enable proxy rotation? (y/N) [${PROXY_DEFAULT}]: " PROXY_CHOICE
PROXY_CHOICE="${PROXY_CHOICE:-$PROXY_DEFAULT}"
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
if [ -z "$YT_ENABLED" ] || [ "$YT_ENABLED" = "false" ]; then
  YT_DEFAULT="n"
else
  YT_DEFAULT="y"
fi
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
if [ -z "$MOBILE_ENABLED" ] || [ "$MOBILE_ENABLED" = "false" ]; then
  MOB_DEFAULT="n"
else
  MOB_DEFAULT="y"
fi
read -p "Use random mobile profile per view? (y/N) [${MOB_DEFAULT}]: " MOB_CHOICE
MOB_CHOICE="${MOB_CHOICE:-$MOB_DEFAULT}"
if [[ "$MOB_CHOICE" =~ ^[yY] ]]; then
  MOBILE_ENABLED="true"
  cfg_set "mobile_profile" true
else
  MOBILE_ENABLED="false"
  cfg_set "mobile_profile" false
fi
# ════════════════════════════════════════════════════════
#  RUN SUMMARY
# ════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              Run Summary                     ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════╣${NC}"
printf "║  %-13s %s\n" "Views:" "$VIEWS"
printf "║  %-13s %s\n" "Key:" "$KEY"
if [ -n "$MULTI_URLS" ]; then
  MULTI_COUNT=$(echo "$MULTI_URLS" | tr ',' '\n' | grep -c '[^ ]' || echo 0)
  printf "║  %-13s %s\n" "Multi-URL:" "\u2713 enabled ($MULTI_COUNT keys)"
fi
if [ "$PROXY_ENABLED" = "true" ]; then
  printf "║  %-13s %s\n" "Proxy:" "\u2713 enabled (${PROXY_TIER})"
else
  printf "║  %-13s %s\n" "Proxy:" "\u2014 disabled"
fi
if [ "$YT_ENABLED" = "true" ]; then
  printf "║  %-13s %s\n" "YouTube src:" "\u2713 enabled"
else
  printf "║  %-13s %s\n" "YouTube src:" "\u2014 disabled"
fi
if [ "$MOBILE_ENABLED" = "true" ]; then
  printf "║  %-13s %s\n" "Mobile prof:" "\u2713 enabled"
else
  printf "║  %-13s %s\n" "Mobile prof:" "\u2014 disabled"
fi
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

read -p "Proceed? (Y/n): " CONFIRM
[[ "$CONFIRM" =~ ^[nN] ]] && { echo "Aborted."; exit 0; }
echo ""

# ════════════════════════════════════════════════════════
#  RUN LOOP
# ════════════════════════════════════════════════════════

export NODE_PATH="${NODE_PATH:+$NODE_PATH:}${SCRIPT_DIR}/node_modules"
export VPLINK_TERMUX="$TERMUX"

TOTAL_OK=0
TOTAL_FAIL=0

for (( i=1; i<=VIEWS; i++ )); do
  echo -e "${BOLD}══════════════════════════════════════════════${NC}"
  echo -e "${BOLD}  View $i of $VIEWS${NC}"
  echo -e "${BOLD}══════════════════════════════════════════════${NC}"
  [ "${VPLINK_TRACE:-0}" = "1" ] && echo "[TRACE] $i: start iteration"

  # ── Clean previous iteration ──────────────────────────
  full_cleanup
  deep_cleanup
  sleep 1

  # ── Pick key ──────────────────────────────────────────
  CURRENT_KEY="$KEY"
  if [ -n "$MULTI_URLS" ]; then
    IFS=',' read -ra URL_ARR <<< "$MULTI_URLS"
    VALID_KEYS=()
    for raw in "${URL_ARR[@]}"; do
      cleaned_key=$(echo "$raw" | sed 's|https\?://vplink.in/||' | sed 's|[/?#].*||' | xargs)
      [ -n "$cleaned_key" ] && VALID_KEYS+=("$cleaned_key")
    done
    if [ ${#VALID_KEYS[@]} -gt 0 ]; then
      RAND_IDX=$(( RANDOM % ${#VALID_KEYS[@]} ))
      CURRENT_KEY="${VALID_KEYS[$RAND_IDX]}"
      info "Picked key ${RAND_IDX}: ${CURRENT_KEY}"
    else
      warn "No valid keys in multi-URL list, using primary key"
    fi
  fi

  # ── Proxy ─────────────────────────────────────────────
  unset VPLINK_PROXY
  if [ "$PROXY_ENABLED" = "true" ]; then
    info "Testing all proxies (clean + speed)..."
    PROXY_RESULT=$(timeout 120 $NODE_BIN "$PROXY_ROTATOR" "$PROXY_TIER" | tail -1) || true
    if [ -n "$PROXY_RESULT" ]; then
      export VPLINK_PROXY="http://${PROXY_RESULT}"
      ok "Proxy: $VPLINK_PROXY"
    else
      warn "No proxy available, running without proxy"
    fi
  fi

  # ── Profile ───────────────────────────────────────────
  unset VPLINK_USER_AGENT VPLINK_VIEWPORT_WIDTH VPLINK_VIEWPORT_HEIGHT VPLINK_REFERER
  if [ "$MOBILE_ENABLED" = "true" ] || [ "$YT_ENABLED" = "true" ]; then
    PROFILE_OUTPUT=$($NODE_BIN "$PROFILE_GENERATOR" "mobile=${MOBILE_ENABLED}" "youtube=${YT_ENABLED}" 2>/dev/null) || true
    if [ -n "$PROFILE_OUTPUT" ]; then
      PROFILE_UA=$(echo "$PROFILE_OUTPUT" | sed -n '1p')
      PROFILE_VIEWPORT=$(echo "$PROFILE_OUTPUT" | sed -n '2p')
      PROFILE_REFERER=$(echo "$PROFILE_OUTPUT" | sed -n '3p')

      [ -n "$PROFILE_UA" ] && export VPLINK_USER_AGENT="$PROFILE_UA"
      VW=$(echo "$PROFILE_VIEWPORT" | cut -d'x' -f1)
      VH=$(echo "$PROFILE_VIEWPORT" | cut -d'x' -f2)
      [ -n "$VW" ] && export VPLINK_VIEWPORT_WIDTH="$VW"
      [ -n "$VH" ] && export VPLINK_VIEWPORT_HEIGHT="$VH"
      if [ "$YT_ENABLED" = "true" ] && [ -n "$PROFILE_REFERER" ]; then
        export VPLINK_REFERER="$PROFILE_REFERER"
        info "YouTube referer: $PROFILE_REFERER"
      fi
    fi
  fi

  # ── Headless mode (Playwright handles everything) ──────
  unset DISPLAY
  export VPLINK_HEADLESS=1

  # ── Run automation ────────────────────────────────────
  [ "${VPLINK_TRACE:-0}" = "1" ] && echo "[TRACE] $i: starting automation"
  info "Starting automation (timeout: 480s)..."

  DEBUG_FLAG=""
  [ "${VPLINK_DEBUG:-0}" = "1" ] && DEBUG_FLAG="--vplink-debug"

  timeout 480 "$NODE_BIN" "$AUTOMATION" "$CURRENT_KEY" ${DEBUG_FLAG:+"$DEBUG_FLAG"}
  EXIT_CODE=$?

  if [ "$EXIT_CODE" -eq 124 ]; then
    warn "Automation timed out after 480s"
    TOTAL_FAIL=$((TOTAL_FAIL + 1))
  elif [ "$EXIT_CODE" -ne 0 ]; then
    warn "View $i failed (exit $EXIT_CODE), skipping..."
    TOTAL_FAIL=$((TOTAL_FAIL + 1))
  fi

  # ── Save result ───────────────────────────────────────
  if [ -f "$SCRIPT_DIR/destination_url.txt" ]; then
    DEST=$(cat "$SCRIPT_DIR/destination_url.txt")
    mv "$SCRIPT_DIR/destination_url.txt" "$SCRIPT_DIR/destination_url_${i}.txt"
    ok "Result $i: $DEST"
    TOTAL_OK=$((TOTAL_OK + 1))
  else
    warn "No destination URL captured for view $i"
  fi
  echo ""
done

# ════════════════════════════════════════════════════════
#  FINAL SUMMARY
# ════════════════════════════════════════════════════════

echo -e "${BOLD}══════════════════════════════════════════════${NC}"
echo -e "${BOLD}  All $VIEWS view(s) completed${NC}"
echo -e "${BOLD}══════════════════════════════════════════════${NC}"

RESULTS=()
for (( i=1; i<=VIEWS; i++ )); do
  if [ -f "$SCRIPT_DIR/destination_url_${i}.txt" ]; then
    URL=$(cat "$SCRIPT_DIR/destination_url_${i}.txt")
    echo "  View $i: $URL"
    RESULTS+=("$URL")
  fi
done

if [ ${#RESULTS[@]} -gt 0 ]; then
  UNIQUE=$(printf '%s\n' "${RESULTS[@]}" | sort -u | wc -l | xargs)
  echo "  ───────────────────────────────────────────"
  echo "  Successful: $TOTAL_OK / $VIEWS"
  echo "  Unique destinations: $UNIQUE / ${#RESULTS[@]}"
else
  echo "  No destinations captured."
fi
echo ""
echo "Results saved in $SCRIPT_DIR/destination_url_*.txt"
