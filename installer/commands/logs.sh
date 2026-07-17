#!/usr/bin/env bash
# installer/commands/logs.sh — Log viewer command
# Displays VPLink 3.0 installation and runtime logs.
# Usage: cmd_logs [--follow] [--lines N]

cmd_logs() {
  set -euo pipefail

  local FOLLOW=false
  local NUM_LINES=50
  local FILTER=""

  while [ $# -gt 0 ]; do
    case "$1" in
      -f|--follow) FOLLOW=true ;;
      -n|--lines)  shift; NUM_LINES="${1:-50}" ;;
      --lines=*)   NUM_LINES="${1#*=}" ;;
      --filter)    shift; FILTER="${1:-}" ;;
      --filter=*)  FILTER="${1#*=}" ;;
      --all)       NUM_LINES=0 ;;
      -h|--help)
        printf "Usage: vplink3.0 logs [OPTIONS]\n\n"
        printf "Options:\n"
        printf "  -f, --follow      Follow log output (tail -f)\n"
        printf "  -n, --lines N     Number of lines to show (default: 50, 0=all)\n"
        printf "  --filter PATTERN   Filter lines matching pattern\n"
        printf "  --all             Show all log lines\n"
        printf "  -h, --help        Show this help\n"
        return 0
        ;;
      *)
        log_warn "Unknown option: $1"
        ;;
    esac
    shift
  done

  local LOG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/.vplink3.0/logs"
  [ -d "$HOME/.vplink3.0/logs" ] && LOG_DIR="$HOME/.vplink3.0/logs"

  if [ ! -d "$LOG_DIR" ]; then
    log_warn "No log directory found at $LOG_DIR"
    log_info "Run 'vplink3.0 install' to generate logs."
    return 1
  fi

  # ── Find log files ──────────────────────────────────────────
  local LOG_FILES=()
  while IFS= read -r -d '' f; do
    LOG_FILES+=("$f")
  done < <(find "$LOG_DIR" -name "*.log" -type f -print0 2>/dev/null | sort -z)

  if [ ${#LOG_FILES[@]} -eq 0 ]; then
    # Check for any files in the directory
    while IFS= read -r -d '' f; do
      LOG_FILES+=("$f")
    done < <(find "$LOG_DIR" -type f -print0 2>/dev/null | sort -z)
  fi

  if [ ${#LOG_FILES[@]} -eq 0 ]; then
    log_warn "No log files found in $LOG_DIR"
    return 1
  fi

  # ── Show available log files ────────────────────────────────
  printf "\033[1mAvailable logs:\033[0m\n"
  local LATEST_LOG="${LOG_FILES[-1]}"
  for lf in "${LOG_FILES[@]}"; do
    local SIZE
    SIZE=$(wc -c < "$lf" 2>/dev/null | tr -d ' ' || echo "?")
    local MOD_TIME
    MOD_TIME=$(stat -c '%Y' "$lf" 2>/dev/null || stat -f '%m' "$lf" 2>/dev/null || echo "0")
    local HUMAN_TIME
    HUMAN_TIME=$(date -d "@$MOD_TIME" '+%Y-%m-%d %H:%M' 2>/dev/null || date -r "$MOD_TIME" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")

    if [ "$lf" = "$LATEST_LOG" ]; then
      printf "  \033[0;32m▶ %s\033[0m (%s bytes, %s) ← latest\n" \
        "$(basename "$lf")" "$SIZE" "$HUMAN_TIME"
    else
      printf "  □ %s (%s bytes, %s)\n" \
        "$(basename "$lf")" "$SIZE" "$HUMAN_TIME"
    fi
  done
  printf "\n"

  # ── Build the display command ───────────────────────────────
  local TARGET_LOG="$LATEST_LOG"

  local CAT_CMD=""
  if [ "$NUM_LINES" -eq 0 ]; then
    CAT_CMD="cat"
  else
    CAT_CMD="tail -n $NUM_LINES"
  fi

  if [ -n "$FILTER" ]; then
    CAT_CMD="$CAT_CMD | grep -i '$FILTER'"
  fi

  if [ "$FOLLOW" = true ]; then
    if [ -n "$FILTER" ]; then
      tail -f -n "$NUM_LINES" "$TARGET_LOG" | grep --line-buffered -i "$FILTER" &
      local TAIL_PID=$!

      trap "kill $TAIL_PID 2>/dev/null; exit 0" INT TERM
      wait $TAIL_PID 2>/dev/null
    else
      tail -f -n "$NUM_LINES" "$TARGET_LOG"
    fi
  else
    printf "\033[1m─── %s (last %s lines) ───\033[0m\n\n" \
      "$(basename "$TARGET_LOG")" "$([ "$NUM_LINES" -eq 0 ] && echo "all" || echo "$NUM_LINES")"

    if [ -n "$FILTER" ]; then
      tail -n "$NUM_LINES" "$TARGET_LOG" 2>/dev/null | grep --color=auto -i "$FILTER" || {
        log_info "No lines matching '$FILTER'"
      }
    else
      tail -n "$NUM_LINES" "$TARGET_LOG" 2>/dev/null || {
        log_warn "Could not read $TARGET_LOG"
      }
    fi
  fi

  return 0
}
