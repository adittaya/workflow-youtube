#!/usr/bin/env bash
# installer/commands/config.sh — Configuration management command
# Manages VPLink 3.0 configuration settings.
# Usage: cmd_config [get|set|list|reset] [key] [value]

cmd_config() {
  set -euo pipefail

  local ACTION="${1:-list}"
  local KEY="${2:-}"
  local VALUE="${3:-}"

  local CONFIG_FILE
  CONFIG_FILE=$(config_path)

  mkdir -p "$(dirname "$CONFIG_FILE")"

  case "$ACTION" in
    list)   _config_list "$CONFIG_FILE" ;;
    get)    _config_get "$CONFIG_FILE" "$KEY" ;;
    set)    _config_set "$CONFIG_FILE" "$KEY" "$VALUE" ;;
    reset)  _config_reset "$CONFIG_FILE" ;;
    export) _config_export "$CONFIG_FILE" ;;
    import) _config_import "$CONFIG_FILE" "$KEY" ;;
    *)
      log_fail "Unknown config action: $ACTION"
      log_info "Usage: vplink3.0 config [get|set|list|reset|export|import]"
      return 1
      ;;
  esac
}

_config_list() {
  set -euo pipefail

  local CONFIG_FILE="$1"

  printf "\n\033[1mVPLink 3.0 Configuration\033[0m\n"
  printf "Config file: %s\n\n" "$CONFIG_FILE"

  if [ ! -f "$CONFIG_FILE" ]; then
    log_warn "No config file found. Using defaults."
    _config_show_defaults
    return 0
  fi

  printf "\033[1m%-30s %s\033[0m\n" "Key" "Value"
  printf "───────────────────────────── ─────────────────────────────\n"

  if has_cmd jq; then
    jq -r 'paths(scalars) as $p | ($p | map(tostring) | join(".")) + " " + (getpath($p) | tostring)' "$CONFIG_FILE" 2>/dev/null | \
    while IFS=' ' read -r key val; do
      printf "  %-28s %s\n" "$key" "$val"
    done
  elif has_cmd python3; then
    python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    data = json.load(f)
def flatten(d, prefix=''):
    for k, v in d.items():
        key = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            flatten(v, key)
        else:
            print(f'  {key:<28} {v}')
flatten(data)
" 2>/dev/null
  else
    while IFS= read -r line; do
      printf "  %s\n" "$line"
    done < "$CONFIG_FILE"
  fi

  printf "\n"
}

_config_get() {
  set -euo pipefail

  local CONFIG_FILE="$1"
  local KEY="$2"

  if [ -z "$KEY" ]; then
    log_fail "Usage: vplink3.0 config get <key>"
    log_info "Example: vplink3.0 config get browser.headless"
    return 1
  fi

  if [ ! -f "$CONFIG_FILE" ]; then
    log_warn "No config file found."
    return 1
  fi

  if has_cmd jq; then
    local VAL
    VAL=$(jq -r --arg key "$KEY" 'getpath($key | split(".")) // empty' "$CONFIG_FILE" 2>/dev/null)
    if [ -n "$VAL" ] && [ "$VAL" != "null" ]; then
      echo "$VAL"
    else
      log_warn "Key '$KEY' not found in config"
      return 1
    fi
  elif has_cmd python3; then
    python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    data = json.load(f)
keys = '$KEY'.split('.')
val = data
for k in keys:
    if isinstance(val, dict) and k in val:
        val = val[k]
    else:
        sys.exit(1)
print(val)
" 2>/dev/null || {
      log_warn "Key '$KEY' not found in config"
      return 1
    }
  else
    log_warn "jq or python3 required for nested config access"
    grep "\"${KEY##*.}\"" "$CONFIG_FILE" 2>/dev/null || {
      log_warn "Key '$KEY' not found in config"
      return 1
    }
  fi
}

_config_set() {
  set -euo pipefail

  local CONFIG_FILE="$1"
  local KEY="$2"
  local VALUE="$3"

  if [ -z "$KEY" ]; then
    log_fail "Usage: vplink3.0 config set <key> <value>"
    log_info "Example: vplink3.0 config set browser.headless true"
    return 1
  fi

  if [ -z "$VALUE" ]; then
    log_fail "Missing value for key '$KEY'"
    return 1
  fi

  # Ensure config file exists with defaults
  if [ ! -f "$CONFIG_FILE" ]; then
    _create_default_config "$CONFIG_FILE"
  fi

  if has_cmd jq; then
    local TMP_FILE
    TMP_FILE=$(mktemp)

    # Build the jq path setter
    local IFS='.'
    read -ra KEY_PARTS <<< "$KEY"

    local SETTER=""
    local CURRENT=""
    for part in "${KEY_PARTS[@]}"; do
      if [ -n "$CURRENT" ]; then
        CURRENT="$CURRENT.$part"
      else
        CURRENT="$part"
      fi
    done

    # Determine value type for JSON
    local JSON_VALUE
    case "${VALUE,,}" in
      true|false)
        JSON_VALUE="$VALUE"
        ;;
      null)
        JSON_VALUE="null"
        ;;
      ''|*[!0-9.]*)
        JSON_VALUE=$(printf '%s' "$VALUE" | jq -Rs '.')
        ;;
      *)
        if echo "$VALUE" | grep -qE '^\-?[0-9]*\.?[0-9]+$'; then
          JSON_VALUE="$VALUE"
        else
          JSON_VALUE=$(printf '%s' "$VALUE" | jq -Rs '.')
        fi
        ;;
    esac

    jq --arg key "$KEY" --argjson val "$JSON_VALUE" '
      ($key | split(".")) as $parts |
      reduce range($parts | length) as $i (
        .;
        if $i == ($parts | length - 1)
        then setpath($parts[$i]; $val)
        else (getpath($parts[$i]) // {}) as $next |
             setpath($parts[$i]; $next)
        end
      )
    ' "$CONFIG_FILE" > "$TMP_FILE" 2>/dev/null

    if [ $? -eq 0 ] && [ -s "$TMP_FILE" ]; then
      mv "$TMP_FILE" "$CONFIG_FILE"
      log_ok "Set $KEY = $VALUE"
    else
      rm -f "$TMP_FILE"
      log_fail "Failed to set config key '$KEY'"
      return 1
    fi

  elif has_cmd python3; then
    python3 -c "
import json, sys

config_file = '$CONFIG_FILE'
key = '$KEY'
value = '$VALUE'

with open(config_file) as f:
    data = json.load(f)

keys = key.split('.')
target = data
for k in keys[:-1]:
    if k not in target or not isinstance(target[k], dict):
        target[k] = {}
    target = target[k]

# Type coercion
v = value
if v.lower() == 'true':
    v = True
elif v.lower() == 'false':
    v = False
elif v.lower() == 'null':
    v = None
elif v.isdigit() or (v.startswith('-') and v[1:].isdigit()):
    v = int(v)
elif v.replace('.', '', 1).isdigit():
    v = float(v)

target[keys[-1]] = v

with open(config_file, 'w') as f:
    json.dump(data, f, indent=2)

print(f'Set {key} = {v}')
" 2>/dev/null || {
      log_fail "Failed to set config key '$KEY' (python3 error)"
      return 1
    }
  else
    log_fail "jq or python3 required for config management"
    return 1
  fi
}

_config_reset() {
  set -euo pipefail

  local CONFIG_FILE="$1"

  if [ -f "$CONFIG_FILE" ]; then
    if ! ui_confirm "Reset config to defaults? Current settings will be lost." "n"; then
      log_info "Config reset cancelled"
      return 0
    fi
  fi

  _create_default_config "$CONFIG_FILE"
  log_ok "Config reset to defaults"
}

_config_export() {
  set -euo pipefail

  local CONFIG_FILE="$1"

  if [ ! -f "$CONFIG_FILE" ]; then
    log_fail "No config file to export"
    return 1
  fi

  cat "$CONFIG_FILE"
}

_config_import() {
  set -euo pipefail

  local CONFIG_FILE="$1"
  local SOURCE="$2"

  if [ -z "$SOURCE" ]; then
    log_fail "Usage: vplink3.0 config import <path-to-json>"
    return 1
  fi

  if [ ! -f "$SOURCE" ]; then
    log_fail "Source file not found: $SOURCE"
    return 1
  fi

  if has_cmd jq; then
    if jq empty "$SOURCE" 2>/dev/null; then
      cp "$SOURCE" "$CONFIG_FILE"
      log_ok "Config imported from $SOURCE"
    else
      log_fail "Invalid JSON in $SOURCE"
      return 1
    fi
  elif has_cmd python3; then
    python3 -c "import json; json.load(open('$SOURCE'))" 2>/dev/null || {
      log_fail "Invalid JSON in $SOURCE"
      return 1
    }
    cp "$SOURCE" "$CONFIG_FILE"
    log_ok "Config imported from $SOURCE"
  else
    cp "$SOURCE" "$CONFIG_FILE"
    log_ok "Config imported from $SOURCE (no JSON validation available)"
  fi
}

_create_default_config() {
  set -euo pipefail

  local CONFIG_FILE="$1"
  mkdir -p "$(dirname "$CONFIG_FILE")"

  cat > "$CONFIG_FILE" <<'DEFAULTS'
{
  "profile": "default",
  "browser": {
    "headless": true,
    "timeout": 60000
  },
  "proxy": {
    "enabled": false,
    "source": "supabase"
  },
  "vnc": {
    "enabled": false,
    "port": 5900
  },
  "install": {
    "version": "3.0.0"
  }
}
DEFAULTS
}

_config_show_defaults() {
  printf "\033[1m%-30s %s\033[0m\n" "Key" "Default"
  printf "───────────────────────────── ─────────────────────────────\n"
  printf "  %-28s %s\n" "profile" "default"
  printf "  %-28s %s\n" "browser.headless" "true"
  printf "  %-28s %s\n" "browser.timeout" "60000"
  printf "  %-28s %s\n" "proxy.enabled" "false"
  printf "  %-28s %s\n" "proxy.source" "supabase"
  printf "  %-28s %s\n" "vnc.enabled" "false"
  printf "  %-28s %s\n" "vnc.port" "5900"
  printf "\n"
}
