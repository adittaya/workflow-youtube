#!/usr/bin/env bash
# installer/commands/uninstall.sh — Clean uninstall command
# Removes VPLink 3.0 completely and cleanly.
# Usage: cmd_uninstall [--all]

cmd_uninstall() {
  set -euo pipefail

  local REMOVE_ALL=false

  while [ $# -gt 0 ]; do
    case "$1" in
      --all) REMOVE_ALL=true ;;
      *) log_warn "Unknown uninstall option: $1" ;;
    esac
    shift
  done

  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"
  local CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/.vplink3.0"
  [ -d "$HOME/.vplink3.0" ] && CONFIG_DIR="$HOME/.vplink3.0"

  ui_progress_init 5 "Uninstalling VPLink 3.0"

  log_info "VPLink 3.0 Uninstaller"
  log_info "Installation dir: $INSTALL_DIR"
  log_info "Config dir:       $CONFIG_DIR\n"

  # ── Step 1: Check for running processes ────────────────────
  ui_progress_update 1 "Checking running processes" "running"

  local RUNNING_PIDS=()
  while IFS= read -r pid; do
    RUNNING_PIDS+=("$pid")
  done < <(pgrep -f "automation\.js\|vplink3\.0\|vplink-desktop" 2>/dev/null || true)

  if [ ${#RUNNING_PIDS[@]} -gt 0 ]; then
    log_warn "Found ${#RUNNING_PIDS[@]} running VPLink process(es):"
    for pid in "${RUNNING_PIDS[@]}"; do
      local CMD_LINE
      CMD_LINE=$(ps -p "$pid" -o args= 2>/dev/null || echo "unknown")
      log_warn "  PID $pid: $CMD_LINE"
    done

    if ui_confirm "Kill all running VPLink processes?" "y"; then
      for pid in "${RUNNING_PIDS[@]}"; do
        kill "$pid" 2>/dev/null && log_ok "  Killed PID $pid" || log_warn "  Could not kill PID $pid"
      done
      sleep 1

      # Force kill any survivors
      for pid in "${RUNNING_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
          kill -9 "$pid" 2>/dev/null || true
        fi
      done
    else
      log_info "  Skipping process termination"
    fi
  else
    log_ok "  No VPLink processes running"
  fi

  ui_progress_update 1 "Checking running processes" "done"

  # ── Step 2: Remove global commands ─────────────────────────
  ui_progress_update 2 "Removing global commands" "running"

  local CMD_REMOVED=0

  for CMD_PATH in "$HOME/.local/bin/vplink3.0" /usr/local/bin/vplink3.0 /usr/bin/vplink3.0; do
    if [ -f "$CMD_PATH" ]; then
      if [ -w "$(dirname "$CMD_PATH")" ] || [ "$IS_ROOT" = true ]; then
        rm -f "$CMD_PATH" 2>/dev/null && {
          log_ok "  Removed $CMD_PATH"
          CMD_REMOVED=$((CMD_REMOVED + 1))
        }
      else
        $SUDO rm -f "$CMD_PATH" 2>/dev/null && {
          log_ok "  Removed $CMD_PATH (via sudo)"
          CMD_REMOVED=$((CMD_REMOVED + 1))
        }
      fi
    fi
  done

  if [ "$CMD_REMOVED" -eq 0 ]; then
    log_info "  No global commands found to remove"
  fi

  ui_progress_update 2 "Removing global commands" "done"

  # ── Step 3: Remove PATH entries from shell profiles ────────
  ui_progress_update 3 "Cleaning PATH entries" "running"

  local PROFILES_CLEANED=0
  local LOCAL_BIN_ESCAPED
  LOCAL_BIN_ESCAPED=$(echo "$HOME/.local/bin" | sed 's/[\/&]/\\&/g')

  for PROFILE in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile" "$HOME/.config/fish/config.fish"; do
    if [ -f "$PROFILE" ]; then
      if grep -q "\.local/bin" "$PROFILE" 2>/dev/null; then
        if ui_confirm "Remove PATH entry from $(basename "$PROFILE")?" "y"; then
          if [[ "$PROFILE" == *.fish ]]; then
            sed -i "\|$HOME/.local/bin|d" "$PROFILE" 2>/dev/null || true
          else
            sed -i "\|export PATH.*\.local/bin|d" "$PROFILE" 2>/dev/null || true
          fi
          PROFILES_CLEANED=$((PROFILES_CLEANED + 1))
          log_ok "  Cleaned $(basename "$PROFILE")"
        fi
      fi
    fi
  done

  if [ "$PROFILES_CLEANED" -eq 0 ]; then
    log_info "  No PATH entries to clean"
  fi

  ui_progress_update 3 "Cleaning PATH entries" "done"

  # ── Step 4: Remove project directory ───────────────────────
  ui_progress_update 4 "Removing project directory" "running"

  if [ "$REMOVE_ALL" = true ]; then
    if [ -d "$INSTALL_DIR" ]; then
      if ui_confirm "Remove project directory ($INSTALL_DIR)?" "y"; then
        rm -rf "$INSTALL_DIR" 2>/dev/null && {
          log_ok "  Removed $INSTALL_DIR"
        } || {
          $SUDO rm -rf "$INSTALL_DIR" 2>/dev/null && {
            log_ok "  Removed $INSTALL_DIR (via sudo)"
          } || {
            log_fail "  Could not remove $INSTALL_DIR"
          }
        }
      fi
    else
      log_info "  Project directory does not exist"
    fi
  else
    log_info "  Keeping project directory (use --all to remove)"
  fi

  ui_progress_update 4 "Removing project directory" "done"

  # ── Step 5: Remove config directory ────────────────────────
  ui_progress_update 5 "Removing config directory" "running"

  if [ "$REMOVE_ALL" = true ]; then
    if [ -d "$CONFIG_DIR" ]; then
      log_warn "\nConfig directory contains:"
      ls -la "$CONFIG_DIR" 2>/dev/null | tail -n +2

      if ui_confirm "Remove config directory ($CONFIG_DIR) including all settings?" "n"; then
        rm -rf "$CONFIG_DIR" 2>/dev/null && {
          log_ok "  Removed $CONFIG_DIR"
        } || {
          log_fail "  Could not remove $CONFIG_DIR"
        }
      else
        log_info "  Keeping config directory"
      fi
    else
      log_info "  Config directory does not exist"
    fi
  else
    log_info "  Keeping config directory (use --all to remove)"
  fi

  ui_progress_update 5 "Removing config directory" "done"

  # ── Cleanup: reset rollback stack ──────────────────────────
  rollback_clear 2>/dev/null || true

  ui_summary \
    "VPLink 3.0 uninstalled" \
    "Commands removed: $CMD_REMOVED" \
    "Profiles cleaned: $PROFILES_CLEANED" \
    "Project removed: $( [ "$REMOVE_ALL" = true ] && echo "yes" || echo "no (use --all)" )" \
    "Config removed: $( [ "$REMOVE_ALL" = true ] && echo "yes" || echo "no (use --all)" )"

  log_ok "Uninstall complete!"
  return 0
}
