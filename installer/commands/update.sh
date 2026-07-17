#!/usr/bin/env bash
# installer/commands/update.sh — Update command
# Pulls latest changes, reinstalls deps if needed.
# Usage: cmd_update

cmd_update() {
  set -euo pipefail

  local INSTALL_DIR="${VPLINK_DIR:-$HOME/vplink3.0}"

  ui_progress_init 6 "Updating VPLink 3.0"
  rollback_init

  # ── Step 1: Check if git repo exists ───────────────────────
  ui_progress_update 1 "Checking repository" "running"

  if [ ! -d "$INSTALL_DIR/.git" ]; then
    ui_progress_update 1 "Checking repository" "fail"
    log_fail "No git repository found at $INSTALL_DIR"
    log_info "Run 'vplink3.0 install' first to set up the project."
    rollback_execute
    return 1
  fi

  ui_progress_update 1 "Checking repository" "done"

  # ── Step 2: Stash local changes ────────────────────────────
  ui_progress_update 2 "Stashing local changes" "running"
  rollback_push "stash"

  local HAS_CHANGES
  HAS_CHANGES=$(git -C "$INSTALL_DIR" status --porcelain 2>/dev/null | wc -l)

  local STASHED=false
  if [ "$HAS_CHANGES" -gt 0 ]; then
    git -C "$INSTALL_DIR" stash push -m "vplink3.0-update-$(date +%s)" --quiet 2>/dev/null || true
    STASHED=true
    log_info "  Stashed $HAS_CHANGES local changes"
  fi

  ui_progress_update 2 "Stashing local changes" "done"

  # ── Step 3: Fetch + pull/reset ──────────────────────────────
  ui_progress_update 3 "Pulling latest changes" "running"
  rollback_push "pull"

  local OLD_COMMIT
  OLD_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")

  git -C "$INSTALL_DIR" fetch --all --quiet 2>/dev/null

  local FETCH_RESULT=$?
  if [ "$FETCH_RESULT" -ne 0 ]; then
    log_warn "  Fetch failed — checking network..."
    if ! _check_connectivity; then
      log_fail "  Network unreachable. Update aborted."
      ui_progress_update 3 "Pulling latest changes" "fail"
      rollback_execute
      return 1
    fi
    git -C "$INSTALL_DIR" fetch --all --quiet 2>/dev/null || {
      log_fail "  Git fetch failed after retry."
      ui_progress_update 3 "Pulling latest changes" "fail"
      rollback_execute
      return 1
    }
  fi

  git -C "$INSTALL_DIR" reset --hard origin/main --quiet 2>/dev/null || {
    git -C "$INSTALL_DIR" pull --ff-only --quiet 2>/dev/null || {
      log_warn "  Could not update to origin/main. Trying origin/master..."
      git -C "$INSTALL_DIR" reset --hard origin/master --quiet 2>/dev/null || true
    }
  }

  local NEW_COMMIT
  NEW_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")

  if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    log_info "  Already up to date ($NEW_COMMIT)"
  else
    log_ok "  Updated: $OLD_COMMIT → $NEW_COMMIT"
  fi

  ui_progress_update 3 "Pulling latest changes" "done"

  # ── Step 4: Reinstall npm deps if package.json changed ──────
  ui_progress_update 4 "Checking npm dependencies" "running"
  rollback_push "npm_update"

  local PKG_DIFF
  PKG_DIFF=$(git -C "$INSTALL_DIR" diff "$OLD_COMMIT".."$NEW_COMMIT" --name-only 2>/dev/null || echo "")

  if echo "$PKG_DIFF" | grep -q "package\.json\|package-lock\.json" 2>/dev/null; then
    log_info "  package.json changed — reinstalling dependencies..."
    (cd "$INSTALL_DIR" && npm install --production 2>&1) || {
      log_warn "  npm install had issues (non-fatal)"
    }
    log_ok "  npm dependencies updated"
  else
    log_info "  package.json unchanged — skipping npm install"
  fi

  ui_progress_update 4 "Checking npm dependencies" "done"

  # ── Step 5: Reinstall Playwright if needed ──────────────────
  ui_progress_update 5 "Checking Playwright" "running"
  rollback_push "playwright_update"

  if [ "${IS_TERMUX:-false}" = true ]; then
    log_info "  Playwright managed externally on Termux"
  elif echo "$PKG_DIFF" | grep -q "package\.json\|package-lock\.json" 2>/dev/null; then
    if [ -d "$INSTALL_DIR/node_modules/playwright" ]; then
      log_info "  Reinstalling Playwright Chromium..."
      (cd "$INSTALL_DIR" && npx playwright install chromium 2>&1) || {
        log_warn "  Playwright Chromium install had issues"
      }
    fi
  else
    log_info "  Playwright unchanged"
  fi

  ui_progress_update 5 "Checking Playwright" "done"

  # ── Step 6: Restore stashed changes + print summary ────────
  ui_progress_update 6 "Finalizing" "running"
  rollback_push "finalize"

  if [ "$STASHED" = true ]; then
    git -C "$INSTALL_DIR" stash pop --quiet 2>/dev/null || {
      log_warn "  Could not restore stashed changes automatically"
      log_info "  Run 'git stash pop' in $INSTALL_DIR to restore them"
    }
  fi

  config_set "update.last_date" "$(date -Iseconds)"
  config_set "update.last_commit" "$NEW_COMMIT"

  rollback_clear
  ui_progress_update 6 "Finalizing" "done"

  ui_summary \
    "VPLink 3.0 updated successfully" \
    "Commit: $OLD_COMMIT → $NEW_COMMIT" \
    "Directory: $INSTALL_DIR"

  log_ok "Update complete!"
  return 0
}

_check_connectivity() {
  if has_cmd curl; then
    curl -sSf --max-time 10 "https://github.com" >/dev/null 2>&1
  elif has_cmd wget; then
    wget -q --timeout=10 --spider "https://github.com" 2>/dev/null
  else
    return 1
  fi
}
