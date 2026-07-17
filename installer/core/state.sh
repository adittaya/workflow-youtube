#!/usr/bin/env bash
# ============================================================================
# state.sh — State Management for Idempotent Installations
# ============================================================================
# Tracks which installation steps have completed. Uses a JSON state file
# so that re-running the installer skips already-done steps.
#
# State file: ~/.config/installer/state.json
# Format: JSON with keys like "sys_deps", "node", "npm_deps", etc.
#
# No external dependencies (no jq) — uses portable heredoc-based JSON.
# ============================================================================

[[ -n "${_STATE_LOADED:-}" ]] && return 0
_STATE_LOADED=1

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_STATE_FILE=""
_STATE_DATA=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Portable config/state directory
_state_config_dir() {
    if [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
        echo "${XDG_CONFIG_HOME}/installer"
    elif [[ "${OS:-}" == "macos" ]]; then
        echo "${HOME}/Library/Application Support/installer"
    elif [[ "${OS:-}" == "windows" ]]; then
        echo "${APPDATA:-$HOME}/installer"
    else
        echo "${HOME}/.config/installer"
    fi
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# state_file — return the path to the state file
state_file_path() { state_file; }
state_file() {
    if [[ -z "$_STATE_FILE" ]]; then
        _STATE_FILE="$(_state_config_dir)/state.json"
    fi
    echo "$_STATE_FILE"
}

# state_load — load state from JSON file
state_load() {
    local fpath
    fpath="$(state_file)"

    if [[ ! -f "$fpath" ]]; then
        _STATE_DATA=""
        return 0
    fi

    _STATE_DATA="$(cat "$fpath" 2>/dev/null || echo "")"
    return 0
}

# state_save — save state to JSON file
state_save() {
    local fpath
    fpath="$(state_file)"
    local dir
    dir="$(dirname "$fpath")"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi

    # If _STATE_DATA is empty, create empty JSON
    if [[ -z "$_STATE_DATA" ]]; then
        _STATE_DATA='{}'
    fi

    printf '%s\n' "$_STATE_DATA" > "$fpath"
    chmod 600 "$fpath"
}

# state_get — get a state value by key
state_get() {
    local key="$1"
    if [[ -z "$_STATE_DATA" ]]; then
        state_load
    fi

    if [[ -z "$_STATE_DATA" ]]; then
        echo ""
        return 1
    fi

    # Portable JSON field extraction without jq
    # Look for "key": "value" pattern
    local value
    value="$(echo "$_STATE_DATA" | _state_json_get "$key")"
    echo "$value"
}

# _state_json_get — portable JSON value extraction
_state_json_get() {
    local key="$1"
    # Handle string values: "key": "value"
    local pattern="\"${key}\"[[:space:]]*:[[:space:]]*\"([^\"]*?)\""
    local result
    result="$(echo "$_STATE_DATA" | grep -oP "$pattern" 2>/dev/null | head -1)"
    if [[ -n "$result" ]]; then
        # Extract the value between quotes
        echo "$result" | sed "s/\"${key}\"[[:space:]]*:[[:space:]]*\"//" | sed 's/"$//'
        return 0
    fi

    # Handle boolean/number values: "key": true/false/123
    pattern="\"${key}\"[[:space:]]*:[[:space:]]*([a-zA-Z0-9]+)"
    result="$(echo "$_STATE_DATA" | grep -oP "$pattern" 2>/dev/null | head -1)"
    if [[ -n "$result" ]]; then
        echo "$result" | sed "s/\"${key}\"[[:space:]]*:[[:space:]]*//"
        return 0
    fi

    return 1
}

# state_set — set a state value
state_set() {
    local key="$1"
    local value="$2"
    if [[ -z "$_STATE_DATA" ]]; then
        state_load
    fi

    # Remove existing key if present, then add new value
    _STATE_DATA="$(_state_json_set "$key" "$value")"
}

# _state_json_set — portable JSON set (rebuild JSON with new value)
_state_json_set() {
    local key="$1"
    local value="$2"

    # Escape double quotes in value
    local escaped_value
    escaped_value="$(echo "$value" | sed 's/"/\\"/g')"

    if [[ -z "$_STATE_DATA" ]] || [[ "$_STATE_DATA" == "{}" ]]; then
        # Empty JSON — create first entry
        printf '{\n  "%s": "%s"\n}' "$key" "$escaped_value"
        return 0
    fi

    # Check if key already exists
    local pattern="\"${key}\"[[:space:]]*:"
    if echo "$_STATE_DATA" | grep -qP "$pattern" 2>/dev/null; then
        # Replace existing value
        # Handle string values
        echo "$_STATE_DATA" | sed -E "s|\"${key}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"|\"${key}\": \"${escaped_value}\"|g"
        return 0
    fi

    # Key doesn't exist — insert before closing brace
    echo "$_STATE_DATA" | sed "s|}|  ,\n  \"${key}\": \"${escaped_value}\"\n}|" 2>/dev/null || \
    echo "$_STATE_DATA" | sed -e "s/}$/  ,\n  \"${key}\": \"${escaped_value}\"\n}/"
}

# state_is_done — check if a step is marked as done
state_is_done() {
    local key="$1"
    local value
    value="$(state_get "$key")"
    [[ "$value" == "done" ]]
}

# state_mark_done — mark a step as done (and save)
state_mark_done() {
    local key="$1"
    state_set "$key" "done"
    state_save
}

# state_clear — clear all state
state_clear() {
    local fpath
    fpath="$(state_file)"
    if [[ -f "$fpath" ]]; then
        rm -f "$fpath"
    fi
    _STATE_DATA=""
    _STATE_FILE=""
}

# state_remove — remove a single key from state
state_remove() {
    local key="$1"
    if [[ -z "$_STATE_DATA" ]]; then
        state_load
    fi

    _STATE_DATA="$(_state_json_remove "$key")"
    state_save
}

# _state_json_remove — portable JSON key removal
_state_json_remove() {
    local key="$1"
    # Remove the key-value pair (handles both string and non-string values)
    # Also removes trailing comma on previous line if needed
    echo "$_STATE_DATA" | sed -E "/\"${key}\"[[:space:]]*:/d" | sed -E ':a;N;$!ba;s|,(\s*\n\s*\})|\1|g'
}

# state_exists — check if state file exists
state_exists() {
    [[ -f "$(state_file)" ]]
}

# state_list — list all state keys and values
state_list() {
    if [[ -z "$_STATE_DATA" ]]; then
        state_load
    fi
    if [[ -z "$_STATE_DATA" ]]; then
        echo "(no state)"
        return 0
    fi
    echo "$_STATE_DATA"
}

# state_init — initialize state file if not present
state_init() {
    local fpath
    fpath="$(state_file)"
    local dir
    dir="$(dirname "$fpath")"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi

    if [[ ! -f "$fpath" ]]; then
        _STATE_DATA="{}"
        state_save
    else
        state_load
    fi
}
