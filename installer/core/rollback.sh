#!/usr/bin/env bash
# ============================================================================
# rollback.sh — Rollback System for Failed Installations
# ============================================================================
# Maintains a stack of rollback actions (shell commands or function names).
# When installation fails, rollback_execute runs all actions in reverse order
# to undo changes.
#
# Actions are stored as strings in a bash array. Each action is either:
#   - A literal shell command string to eval
#   - A function name (called without arguments)
# ============================================================================

[[ -n "${_ROLLBACK_LOADED:-}" ]] && return 0
_ROLLBACK_LOADED=1

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_ROLLBACK_STACK=()     # Array of "action|||description" strings
_ROLLBACK_INITIALIZED=0

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# rollback_init — initialize the rollback stack (clear any existing actions)
rollback_init() {
    _ROLLBACK_STACK=()
    _ROLLBACK_INITIALIZED=1
}

# rollback_push — register a rollback action
# Arguments:
#   $1 — action: a shell command string OR function name
#   $2 — description (human-readable, for logging)
# Example:
#   rollback_push "rm -rf /tmp/mybuild" "Remove temporary build dir"
#   rollback_push "restore_config" "Restore original config file"
rollback_push() {
    local action="$1"
    local description="${2:-No description}"

    if [[ -z "$action" ]]; then
        echo "Warning: rollback_push called with empty action" >&2
        return 1
    fi

    _ROLLBACK_STACK+=("${action}|||${description}")
}

# rollback_pop — execute and remove the last rollback action
rollback_pop() {
    if [[ ${#_ROLLBACK_STACK[@]} -eq 0 ]]; then
        echo "Rollback stack is empty."
        return 0
    fi

    # Get last element
    local last_index=$(( ${#_ROLLBACK_STACK[@]} - 1 ))
    local entry="${_ROLLBACK_STACK[$last_index]}"
    local action="${entry%%|||*}"
    local description="${entry#*|||}"

    echo "Rolling back: $description"
    _rollback_run_action "$action"

    # Remove last element
    unset '_ROLLBACK_STACK[last_index]'
    # Re-index the array
    _ROLLBACK_STACK=("${_ROLLBACK_STACK[@]+"${_ROLLBACK_STACK[@]}"}")
}

# rollback_execute — execute ALL rollback actions in reverse order
rollback_execute() {
    local count=${#_ROLLBACK_STACK[@]}

    if [[ $count -eq 0 ]]; then
        echo "Rollback stack is empty — nothing to undo."
        return 0
    fi

    echo ""
    echo "=========================================="
    echo "  Executing rollback ($count actions)"
    echo "=========================================="

    local failed=0
    while [[ ${#_ROLLBACK_STACK[@]} -gt 0 ]]; do
        rollback_pop || failed=$(( failed + 1 ))
    done

    echo "=========================================="
    if [[ $failed -gt 0 ]]; then
        echo "  Rollback completed with $failed failure(s)"
        echo "=========================================="
        return 1
    else
        echo "  Rollback completed successfully"
        echo "=========================================="
        return 0
    fi
}

# rollback_clear — clear the rollback stack (discard all actions)
rollback_clear() {
    _ROLLBACK_STACK=()
}

# rollback_count — return the number of pending rollback actions
rollback_count() {
    echo ${#_ROLLBACK_STACK[@]}
}

# rollback_list — list all pending rollback actions
rollback_list() {
    local count=${#_ROLLBACK_STACK[@]}
    if [[ $count -eq 0 ]]; then
        echo "(no pending rollback actions)"
        return 0
    fi

    echo "Pending rollback actions ($count):"
    local i
    for i in $(seq 0 $(( count - 1 ))); do
        local entry="${_ROLLBACK_STACK[$i]}"
        local description="${entry#*|||}"
        echo "  $((i+1)). $description"
    done
}

# rollback_peek — show the last registered action without executing
rollback_peek() {
    if [[ ${#_ROLLBACK_STACK[@]} -eq 0 ]]; then
        echo "(empty)"
        return 0
    fi

    local last_index=$(( ${#_ROLLBACK_STACK[@]} - 1 ))
    local entry="${_ROLLBACK_STACK[$last_index]}"
    local action="${entry%%|||*}"
    local description="${entry#*|||}"

    echo "Last action: $description"
    echo "Command: $action"
}

# rollback_run_on_exit — set up trap to run rollback on script exit
rollback_run_on_exit() {
    trap '_rollback_on_exit_handler' EXIT INT TERM
}

# rollback_install_file — convenience: push a rollback to remove an installed file/dir
rollback_install_file() {
    local target="$1"
    local description="${2:-Remove $target}"

    if [[ -e "$target" ]]; then
        rollback_push "rm -rf '$target'" "$description"
    fi
}

# rollback_install_backup — convenience: push a rollback to restore a backed-up file
rollback_install_backup() {
    local original="$1"
    local backup="${original}.backup"
    local description="${2:-Restore $original from backup}"

    if [[ -f "$backup" ]]; then
        rollback_push "cp '$backup' '$original'" "$description"
    fi
}

# rollback_install_apt_package — convenience: push a rollback to remove an apt package
rollback_install_apt_package() {
    local pkg="$1"
    local description="${2:-Remove apt package $pkg}"
    rollback_push "apt-get remove -y '$pkg'" "$description"
}

# rollback_install_path_line — convenience: push a rollback to remove a PATH line
rollback_install_path_line() {
    local dir="$1"
    local profile="${2:-$(env_get_profile)}"
    local description="${3:-Remove $dir from PATH}"
    rollback_push "grep -v '$dir' '$profile' > '${profile}.tmp' && mv '${profile}.tmp' '$profile'" "$description"
}

# ---------------------------------------------------------------------------
# Internal: run a single action
# ---------------------------------------------------------------------------
_rollback_run_action() {
    local action="$1"

    # Check if it's a function name
    if declare -f "$action" >/dev/null 2>&1; then
        "$action"
        return $?
    fi

    # Otherwise, eval as a shell command
    eval "$action" 2>&1
    local result=$?

    if [[ $result -ne 0 ]]; then
        echo "Warning: Rollback action failed (exit code $result): $action" >&2
    fi

    return $result
}

# ---------------------------------------------------------------------------
# Internal: trap handler
# ---------------------------------------------------------------------------
_rollback_on_exit_handler() {
    local exit_code=$?
    if [[ ${#_ROLLBACK_STACK[@]} -gt 0 ]]; then
        echo ""
        echo "Script exited with code $exit_code — running rollback..."
        rollback_execute || true
    fi
}
