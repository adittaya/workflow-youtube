#!/usr/bin/env bash
# ============================================================================
# logger.sh — Logging System with Multiple Levels and Output Targets
# ============================================================================
# Provides colored console output, timestamped file logging, and summary
# tracking. Detects TTY for color support; disables colors in non-interactive
# or piped contexts.
# ============================================================================

[[ -n "${_LOGGER_LOADED:-}" ]] && return 0
_LOGGER_LOADED=1

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_LOGGER_FILE=""
_LOGGER_OK_COUNT=0
_LOGGER_WARN_COUNT=0
_LOGGER_FAIL_COUNT=0
_LOGGER_INFO_COUNT=0
_LOGGER_DEBUG_COUNT=0

# ---------------------------------------------------------------------------
# Color detection
# ---------------------------------------------------------------------------
_logger_has_color() {
    if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]] && [[ "${TERM:-}" != "dumb" ]]; then
        return 0
    fi
    return 1
}

if _logger_has_color; then
    _LC_GREEN='\033[0;32m'
    _LC_YELLOW='\033[0;33m'
    _LC_RED='\033[0;31m'
    _LC_CYAN='\033[0;36m'
    _LC_GRAY='\033[0;90m'
    _LC_BOLD='\033[1m'
    _LC_RESET='\033[0m'
    _LC_CHECK='✔'
    _LC_WARN='⚠'
    _LC_FAIL='✘'
    _LC_INFO='ℹ'
else
    _LC_GREEN=''
    _LC_YELLOW=''
    _LC_RED=''
    _LC_CYAN=''
    _LC_GRAY=''
    _LC_BOLD=''
    _LC_RESET=''
    _LC_CHECK='[OK]'
    _LC_WARN='[WARN]'
    _LC_FAIL='[FAIL]'
    _LC_INFO='[INFO]'
fi

# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------
_logger_timestamp() {
    date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "0000-00-00 00:00:00"
}

# ---------------------------------------------------------------------------
# Internal: write to log file if set
# ---------------------------------------------------------------------------
_log_to_file() {
    local level="$1"
    local msg="$2"
    if [[ -n "$_LOGGER_FILE" ]] && [[ -w "$(dirname "$_LOGGER_FILE")" ]]; then
        echo "[$(_logger_timestamp)] [$level] $msg" >> "$_LOGGER_FILE"
    fi
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# log_file — set the log file path
logger_file() { log_file "$@"; }
log_file() {
    _LOGGER_FILE="$1"
    local dir
    dir="$(dirname "$_LOGGER_FILE")"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi
    # Initialize file with header
    echo "# VPLink Installer Log — Started $(_logger_timestamp)" > "$_LOGGER_FILE"
}

# log_ok — success message (green checkmark)
logger_ok() { log_ok "$@"; }
log_ok() {
    local msg="$1"
    _LOGGER_OK_COUNT=$(( _LOGGER_OK_COUNT + 1 ))
    _log_to_file "OK" "$msg"
    printf "${_LC_GREEN}  ${_LC_CHECK}  %s${_LC_RESET}\n" "$msg"
}

# log_warn — warning message (yellow warning)
logger_warn() { log_warn "$@"; }
log_warn() {
    local msg="$1"
    _LOGGER_WARN_COUNT=$(( _LOGGER_WARN_COUNT + 1 ))
    _log_to_file "WARN" "$msg"
    printf "${_LC_YELLOW}  ${_LC_WARN}  %s${_LC_RESET}\n" "$msg"
}

# log_fail — error message (red X)
logger_fail() { log_fail "$@"; }
log_fail() {
    local msg="$1"
    _LOGGER_FAIL_COUNT=$(( _LOGGER_FAIL_COUNT + 1 ))
    _log_to_file "FAIL" "$msg"
    printf "${_LC_RED}  ${_LC_FAIL}  %s${_LC_RESET}\n" "$msg"
}

# log_info — info message (cyan)
logger_info() { log_info "$@"; }
log_info() {
    local msg="$1"
    _LOGGER_INFO_COUNT=$(( _LOGGER_INFO_COUNT + 1 ))
    _log_to_file "INFO" "$msg"
    printf "${_LC_CYAN}  ${_LC_INFO}  %s${_LC_RESET}\n" "$msg"
}

# log_step — step progress: [1/8] Step name
logger_step() { log_step "$@"; }
log_step() {
    local num="$1"
    local total="$2"
    local msg="$3"
    _log_to_file "STEP" "[$num/$total] $msg"
    printf "\n${_LC_BOLD}[$num/$total]${_LC_RESET} ${_LC_BOLD}%s${_LC_RESET}\n" "$msg"
    printf "${_LC_GRAY}%s${_LC_RESET}\n" "$(printf '%0.s─' $(seq 1 50))"
}

# log_debug — debug message (only when DEBUG=1)
logger_debug() { log_debug "$@"; }
log_debug() {
    local msg="$1"
    _LOGGER_DEBUG_COUNT=$(( _LOGGER_DEBUG_COUNT + 1 ))
    _log_to_file "DEBUG" "$msg"
    if [[ "${DEBUG:-0}" -eq 1 ]] || [[ "${INSTALLER_DEBUG:-0}" -eq 1 ]]; then
        printf "${_LC_GRAY}  [DEBUG]  %s${_LC_RESET}\n" "$msg"
    fi
}

# log_raw — raw output (no prefix or color)
logger_raw() { log_raw "$@"; }
log_raw() {
    local msg="$1"
    _log_to_file "RAW" "$msg"
    printf "%s\n" "$msg"
}

# log_raw_no_nl — raw output without newline
logger_raw_no_nl() { log_raw_no_nl "$@"; }
log_raw_no_nl() {
    local msg="$1"
    printf "%s" "$msg"
}

# log_error — alias for log_fail (for clarity in error handling)
logger_error() { log_error "$@"; }
log_error() {
    log_fail "$1"
}

# log_fatal — log failure and exit
logger_fatal() { log_fatal "$@"; }
log_fatal() {
    local msg="$1"
    local code="${2:-1}"
    log_fail "FATAL: $msg"
    _log_to_file "FATAL" "$msg"
    exit "$code"
}

# log_summary — print summary of warnings and errors
logger_summary() { log_summary; }
log_summary() {
    echo ""
    printf "${_LC_BOLD}========================================${_LC_RESET}\n"
    printf "${_LC_BOLD}  Installation Summary${_LC_RESET}\n"
    printf "${_LC_BOLD}========================================${_LC_RESET}\n"

    if [[ $_LOGGER_OK_COUNT -gt 0 ]]; then
        printf "  ${_LC_GREEN}${_LC_CHECK} Successes: %d${_LC_RESET}\n" "$_LOGGER_OK_COUNT"
    fi
    if [[ $_LOGGER_INFO_COUNT -gt 0 ]]; then
        printf "  ${_LC_CYAN}${_LC_INFO} Info:      %d${_LC_RESET}\n" "$_LOGGER_INFO_COUNT"
    fi
    if [[ $_LOGGER_WARN_COUNT -gt 0 ]]; then
        printf "  ${_LC_YELLOW}${_LC_WARN} Warnings:  %d${_LC_RESET}\n" "$_LOGGER_WARN_COUNT"
    fi
    if [[ $_LOGGER_FAIL_COUNT -gt 0 ]]; then
        printf "  ${_LC_RED}${_LC_FAIL} Errors:    %d${_LC_RESET}\n" "$_LOGGER_FAIL_COUNT"
    fi
    if [[ "${DEBUG:-0}" -eq 1 ]] && [[ $_LOGGER_DEBUG_COUNT -gt 0 ]]; then
        printf "  ${_LC_GRAY}  Debug:     %d${_LC_RESET}\n" "$_LOGGER_DEBUG_COUNT"
    fi

    printf "${_LC_BOLD}========================================${_LC_RESET}\n"

    if [[ -n "$_LOGGER_FILE" ]]; then
        printf "  Log file: %s\n" "$_LOGGER_FILE"
    fi
    echo ""

    # Return non-zero if there were errors
    if [[ $_LOGGER_FAIL_COUNT -gt 0 ]]; then
        return 1
    fi
    return 0
}

# log_reset_counts — reset all counters
logger_reset_counts() { log_reset_counts; }
log_reset_counts() {
    _LOGGER_OK_COUNT=0
    _LOGGER_WARN_COUNT=0
    _LOGGER_FAIL_COUNT=0
    _LOGGER_INFO_COUNT=0
    _LOGGER_DEBUG_COUNT=0
}

# log_set_level — set minimum log level (ok, warn, fail, info, debug, all)
logger_set_level() { log_set_level "$@"; }
log_set_level() {
    _LOGGER_LEVEL="${1:-all}"
}
_LOGGER_LEVEL="all"
