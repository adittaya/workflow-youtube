#!/usr/bin/env bash
# ============================================================================
# config.sh — Configuration Management
# ============================================================================
# Stores installer configuration in a platform-standard JSON file.
# Supports get/set/has/init/load/save operations.
#
# Config locations:
#   Linux/macOS/Termux: ~/.config/installer/config.json
#   Windows:            %APPDATA%/installer/config.json
#
# No external dependencies (no jq) — uses portable JSON operations.
# ============================================================================

[[ -n "${_CONFIG_LOADED:-}" ]] && return 0
_CONFIG_LOADED=1

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_CONFIG_FILE=""
_CONFIG_DATA=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_config_dir() {
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

# config_path — return the config file path
config_file_path() { config_path; }
config_path() {
    if [[ -z "$_CONFIG_FILE" ]]; then
        _CONFIG_FILE="$(_config_dir)/config.json"
    fi
    echo "$_CONFIG_FILE"
}

# config_dir — return the config directory
config_get_dir() { config_dir; }
config_dir() {
    echo "$(_config_dir)"
}

# config_load — load config from file
config_load() {
    local fpath
    fpath="$(config_path)"

    if [[ ! -f "$fpath" ]]; then
        _CONFIG_DATA=""
        return 0
    fi

    _CONFIG_DATA="$(cat "$fpath" 2>/dev/null || echo "")"
    return 0
}

# config_save — save config to file
config_save() {
    local fpath
    fpath="$(config_path)"
    local dir
    dir="$(dirname "$fpath")"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi

    if [[ -z "$_CONFIG_DATA" ]]; then
        _CONFIG_DATA='{}'
    fi

    printf '%s\n' "$_CONFIG_DATA" > "$fpath"
    chmod 600 "$fpath"
}

# config_get — get a config value by key
config_get() {
    local key="$1"
    if [[ -z "$_CONFIG_DATA" ]]; then
        config_load
    fi

    if [[ -z "$_CONFIG_DATA" ]]; then
        echo ""
        return 1
    fi

    local value
    value="$(_config_json_get "$key")"
    echo "$value"
}

# _config_json_get — portable JSON value extraction
_config_json_get() {
    local key="$1"

    # Handle string values: "key": "value"
    local pattern="\"${key}\"[[:space:]]*:[[:space:]]*\"([^\"]*?)\""
    local result
    result="$(echo "$_CONFIG_DATA" | grep -oP "$pattern" 2>/dev/null | head -1)"
    if [[ -n "$result" ]]; then
        echo "$result" | sed "s/\"${key}\"[[:space:]]*:[[:space:]]*\"//" | sed 's/"$//'
        return 0
    fi

    # Handle boolean/number values: "key": true/false/123
    pattern="\"${key}\"[[:space:]]*:[[:space:]]*([a-zA-Z0-9._-]+)"
    result="$(echo "$_CONFIG_DATA" | grep -oP "$pattern" 2>/dev/null | head -1)"
    if [[ -n "$result" ]]; then
        echo "$result" | sed "s/\"${key}\"[[:space:]]*:[[:space:]]*//"
        return 0
    fi

    return 1
}

# config_set — set a config value
config_set() {
    local key="$1"
    local value="$2"
    if [[ -z "$_CONFIG_DATA" ]]; then
        config_load
    fi

    _CONFIG_DATA="$(_config_json_set "$key" "$value")"
}

# _config_json_set — portable JSON set
_config_json_set() {
    local key="$1"
    local value="$2"

    # Escape double quotes in value
    local escaped_value
    escaped_value="$(echo "$value" | sed 's/"/\\"/g')"

    if [[ -z "$_CONFIG_DATA" ]] || [[ "$_CONFIG_DATA" == "{}" ]]; then
        printf '{\n  "%s": "%s"\n}' "$key" "$escaped_value"
        return 0
    fi

    # Check if key already exists
    local pattern="\"${key}\"[[:space:]]*:"
    if echo "$_CONFIG_DATA" | grep -qP "$pattern" 2>/dev/null; then
        # Replace existing value
        echo "$_CONFIG_DATA" | sed -E "s|\"${key}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"|\"${key}\": \"${escaped_value}\"|g"
        return 0
    fi

    # Key doesn't exist — insert before closing brace
    echo "$_CONFIG_DATA" | sed "s|}|  ,\n  \"${key}\": \"${escaped_value}\"\n}|" 2>/dev/null || \
    echo "$_CONFIG_DATA" | sed -e "s/}$/  ,\n  \"${key}\": \"${escaped_value}\"\n}/"
}

# config_has — check if a key exists in config
config_has() {
    local key="$1"
    if [[ -z "$_CONFIG_DATA" ]]; then
        config_load
    fi

    if [[ -z "$_CONFIG_DATA" ]]; then
        return 1
    fi

    local pattern="\"${key}\"[[:space:]]*:"
    echo "$_CONFIG_DATA" | grep -qP "$pattern" 2>/dev/null
}

# config_remove — remove a key from config
config_remove() {
    local key="$1"
    if [[ -z "$_CONFIG_DATA" ]]; then
        config_load
    fi

    _CONFIG_DATA="$(_config_json_remove "$key")"
    config_save
}

# _config_json_remove — portable JSON key removal
_config_json_remove() {
    local key="$1"
    echo "$_CONFIG_DATA" | sed -E "/\"${key}\"[[:space:]]*:/d" | sed -E ':a;N;$!ba;s|,(\s*\n\s*\})|\1|g'
}

# config_init — create default config
config_init() {
    local fpath
    fpath="$(config_path)"
    local dir
    dir="$(dirname "$fpath")"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi

    if [[ ! -f "$fpath" ]]; then
        _CONFIG_DATA='{
  "version": "3.0",
  "install_dir": "",
  "vplink_home": "",
  "auto_update": true,
  "debug": false,
  "log_level": "info",
  "node_version": "lts"
}'
        config_save
    else
        config_load
    fi
}

# config_list — dump entire config
config_list() {
    if [[ -z "$_CONFIG_DATA" ]]; then
        config_load
    fi
    if [[ -z "$_CONFIG_DATA" ]]; then
        echo "(no config)"
        return 0
    fi
    echo "$_CONFIG_DATA"
}

# config_reset — reset config to defaults
config_reset() {
    local fpath
    fpath="$(config_path)"
    rm -f "$fpath"
    _CONFIG_DATA=""
    config_init
}

# config_backup — backup current config
config_backup() {
    local fpath
    fpath="$(config_path)"
    if [[ -f "$fpath" ]]; then
        cp "$fpath" "${fpath}.backup.$(date +%s)"
    fi
}
