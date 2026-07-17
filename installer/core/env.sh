#!/usr/bin/env bash
# ============================================================================
# env.sh — Environment Variable and PATH Management
# ============================================================================
# Manages shell profiles (.bashrc, .zshrc, .profile, .bash_profile,
# fish config, PowerShell profile) for:
#   - PATH additions/removals
#   - Environment variable setting/unsetting
#   - Idempotent line management (no duplicates)
#   - Safe modification with backup
#
# Requires: platform.sh (for OS, SHELL_TYPE detection)
# ============================================================================

[[ -n "${_ENV_LOADED:-}" ]] && return 0
_ENV_LOADED=1

# ---------------------------------------------------------------------------
# Internal: get the user's shell profile file
# ---------------------------------------------------------------------------
_env_detect_profile() {
    local shell_name="${SHELL_TYPE:-unknown}"

    case "$shell_name" in
        bash)
            # Prefer .bashrc on Linux, .bash_profile on macOS
            if [[ "${OS:-}" == "macos" ]]; then
                if [[ -f "${HOME}/.bash_profile" ]]; then
                    echo "${HOME}/.bash_profile"
                elif [[ -f "${HOME}/.bashrc" ]]; then
                    echo "${HOME}/.bashrc"
                else
                    echo "${HOME}/.bash_profile"
                fi
            else
                if [[ -f "${HOME}/.bashrc" ]]; then
                    echo "${HOME}/.bashrc"
                elif [[ -f "${HOME}/.bash_profile" ]]; then
                    echo "${HOME}/.bash_profile"
                else
                    echo "${HOME}/.bashrc"
                fi
            fi
            ;;
        zsh)
            echo "${HOME}/.zshrc"
            ;;
        fish)
            echo "${HOME}/.config/fish/config.fish"
            ;;
        powershell)
            if has_cmd pwsh; then
                local profile_path
                profile_path="$(pwsh -NoProfile -Command '$PROFILE' 2>/dev/null || echo "${HOME}/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")"
                echo "$profile_path"
            else
                echo "${HOME}/Documents/PowerShell/Microsoft.PowerShell_profile.ps1"
            fi
            ;;
        sh)
            # sh uses .profile
            if [[ -f "${HOME}/.profile" ]]; then
                echo "${HOME}/.profile"
            else
                echo "${HOME}/.profile"
            fi
            ;;
        *)
            # Fallback: try common profiles
            if [[ -f "${HOME}/.profile" ]]; then
                echo "${HOME}/.profile"
            elif [[ -f "${HOME}/.bashrc" ]]; then
                echo "${HOME}/.bashrc"
            elif [[ -f "${HOME}/.zshrc" ]]; then
                echo "${HOME}/.zshrc"
            else
                echo "${HOME}/.profile"
            fi
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# env_get_profile — detect and return user's shell profile path
env_get_profile() {
    _env_detect_profile
}

# env_add_path — add directory to PATH in shell profile
env_add_path() {
    local dir="$1"

    if [[ -z "$dir" ]]; then
        echo "Error: env_add_path requires a directory" >&2
        return 1
    fi

    # Already in current PATH?
    if env_path_contains "$dir"; then
        echo "Directory already in PATH: $dir"
        return 0
    fi

    local profile
    profile="$(env_get_profile)"
    local profile_dir
    profile_dir="$(dirname "$profile")"

    # Ensure profile directory exists
    if [[ ! -d "$profile_dir" ]]; then
        mkdir -p "$profile_dir"
    fi

    # Backup before modification
    env_backup_profile

    # Add to current session PATH
    export PATH="${dir}:${PATH}"

    # Add to profile file (idempotent)
    if [[ "${SHELL_TYPE:-}" == "fish" ]]; then
        # Fish uses set -gx PATH ...
        local fish_line="set -gx PATH \"$dir\" \$PATH"
        _env_ensure_line "$profile" "$fish_line"
    elif [[ "${SHELL_TYPE:-}" == "powershell" ]]; then
        # PowerShell uses $env:Path
        local ps_line="\$env:Path = \"$dir\" + \$env:Path"
        _env_ensure_line "$profile" "$ps_line"
    else
        # POSIX shells: export PATH=...
        local bash_line="export PATH=\"${dir}:\${PATH}\""
        _env_ensure_line "$profile" "$bash_line"
    fi

    echo "Added $dir to PATH in $profile"
}

# env_remove_path — remove directory from PATH in shell profile
env_remove_path() {
    local dir="$1"

    if [[ -z "$dir" ]]; then
        echo "Error: env_remove_path requires a directory" >&2
        return 1
    fi

    local profile
    profile="$(env_get_profile)"

    # Remove from current session PATH
    local cleaned_path
    cleaned_path="$(echo "$PATH" | tr ':' '\n' | grep -v "^${dir}$" | tr '\n' ':' | sed 's/:$//')"
    export PATH="$cleaned_path"

    # Remove from profile file
    if [[ -f "$profile" ]]; then
        env_backup_profile

        if [[ "${SHELL_TYPE:-}" == "fish" ]]; then
            _env_remove_pattern "$profile" "set -gx PATH.*${dir}"
        elif [[ "${SHELL_TYPE:-}" == "powershell" ]]; then
            # shellcheck disable=SC2154
            _env_remove_pattern "$profile" ".*${dir}.*\\$env:Path"
        else
            _env_remove_pattern "$profile" "export PATH=.*${dir}"
        fi
    fi

    echo "Removed $dir from PATH"
}

# env_set — set an environment variable in shell profile
env_set() {
    local key="$1"
    local value="$2"

    if [[ -z "$key" ]]; then
        echo "Error: env_set requires a key" >&2
        return 1
    fi

    local profile
    profile="$(env_get_profile)"
    local profile_dir
    profile_dir="$(dirname "$profile")"

    if [[ ! -d "$profile_dir" ]]; then
        mkdir -p "$profile_dir"
    fi

    # Backup before modification
    env_backup_profile

    # Export in current session
    export "$key=$value"

    # Remove existing declaration from profile
    if [[ -f "$profile" ]]; then
        _env_remove_pattern "$profile" "export ${key}="
    fi

    # Add to profile
    if [[ "${SHELL_TYPE:-}" == "fish" ]]; then
        local fish_line="set -gx $key \"$value\""
        _env_ensure_line "$profile" "$fish_line"
    elif [[ "${SHELL_TYPE:-}" == "powershell" ]]; then
        local ps_line="\$env:${key} = \"$value\""
        _env_ensure_line "$profile" "$ps_line"
    else
        local bash_line="export ${key}=\"${value}\""
        _env_ensure_line "$profile" "$bash_line"
    fi

    echo "Set $key=$value in $profile"
}

# env_unset — remove an environment variable from shell profile
env_unset() {
    local key="$1"

    if [[ -z "$key" ]]; then
        echo "Error: env_unset requires a key" >&2
        return 1
    fi

    # Unset from current session
    unset "$key" 2>/dev/null || true

    local profile
    profile="$(env_get_profile)"

    if [[ -f "$profile" ]]; then
        env_backup_profile

        if [[ "${SHELL_TYPE:-}" == "fish" ]]; then
            _env_remove_pattern "$profile" "set -gx $key"
        elif [[ "${SHELL_TYPE:-}" == "powershell" ]]; then
            _env_remove_pattern "$profile" "\\$env:${key}"
        else
            _env_remove_pattern "$profile" "export ${key}="
        fi
    fi

    echo "Unset $key from $profile"
}

# env_ensure_line — add a line to a file if not already present
env_ensure_line() {
    local file="$1"
    local line="$2"
    _env_ensure_line "$file" "$line"
}

_env_ensure_line() {
    local file="$1"
    local line="$2"

    if [[ ! -f "$file" ]]; then
        # Ensure directory exists
        local dir
        dir="$(dirname "$file")"
        mkdir -p "$dir"
        echo "$line" >> "$file"
        return 0
    fi

    # Check if line already exists (exact match)
    if grep -qxF "$line" "$file" 2>/dev/null; then
        return 0
    fi

    # Add line with trailing newline
    echo "" >> "$file"
    echo "$line" >> "$file"
}

# env_remove_line — remove lines matching a pattern from a file
env_remove_line() {
    local file="$1"
    local pattern="$2"
    _env_remove_pattern "$file" "$pattern"
}

_env_remove_pattern() {
    local file="$1"
    local pattern="$2"

    if [[ ! -f "$file" ]]; then
        return 0
    fi

    # Use sed to remove matching lines
    local tmpfile
    tmpfile="$(mktemp)"
    grep -v "$pattern" "$file" > "$tmpfile" 2>/dev/null || true
    mv "$tmpfile" "$file"
}

# env_path_contains — check if current PATH contains a directory
env_path_contains() {
    local dir="$1"
    echo ":$PATH:" | grep -q ":${dir}:"
}

# env_source_profile — source the user's shell profile
env_source_profile() {
    local profile
    profile="$(env_get_profile)"

    if [[ -f "$profile" ]]; then
        # shellcheck disable=SC1090
        source "$profile" 2>/dev/null || true
    fi
}

# env_backup_profile — create a timestamped backup of the shell profile
env_backup_profile() {
    local profile
    profile="$(env_get_profile)"

    if [[ -f "$profile" ]]; then
        local backup
        backup="${profile}.backup.$(date +%s)"
        cp "$profile" "$backup"
        echo "Backed up $profile -> $backup"
    fi
}

# env_list_paths — list all PATH entries
env_list_paths() {
    echo "$PATH" | tr ':' '\n'
}

# env_current — show current env vars managed by installer
env_current() {
    echo "PATH entries:"
    env_list_paths | while read -r p; do
        if [[ -d "$p" ]]; then
            echo "  ✓ $p"
        else
            echo "  ✗ $p (missing)"
        fi
    done
    echo ""
    echo "Shell: ${SHELL_TYPE:-unknown}"
    echo "Profile: $(env_get_profile)"
}
