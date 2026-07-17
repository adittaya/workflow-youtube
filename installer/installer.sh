#!/usr/bin/env bash
# ============================================================================
# installer.sh — VPLink 3.0 Cross-Platform Bootstrap Installer
# ============================================================================
# Usage:
#   curl -fsSL <url> | bash -s -- install
#   ./installer.sh install
#   ./installer.sh help
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
INSTALLER_VERSION="3.0.0"
INSTALLER_NAME="vplink3.0-installer"

# ---------------------------------------------------------------------------
# Determine INSTALLER_DIR (where this script lives)
# ---------------------------------------------------------------------------
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If piped via curl, BASH_SOURCE[0] may be empty or /dev/stdin.
# In that case, we need a temp extraction or use the current directory.
if [[ -z "${INSTALLER_DIR:-}" || "${INSTALLER_DIR}" == "/dev" || "${INSTALLER_DIR}" == "." ]]; then
    INSTALLER_DIR="$(pwd)"
fi

# Verify the installer directory has the expected structure
if [[ ! -d "${INSTALLER_DIR}/core" ]]; then
    echo "ERROR: Cannot find installer core modules at ${INSTALLER_DIR}/core" >&2
    echo "       Run from the installer/ directory or set INSTALLER_DIR." >&2
    exit 1
fi

export INSTALLER_DIR

# ---------------------------------------------------------------------------
# Color setup
# ---------------------------------------------------------------------------
if [[ -t 1 ]] && [[ "${NO_COLOR:-0}" != "1" ]]; then
    _CLR_BOLD='\033[1m'
    _CLR_DIM='\033[2m'
    _CLR_GREEN='\033[0;32m'
    _CLR_YELLOW='\033[1;33m'
    _CLR_RED='\033[0;31m'
    _CLR_CYAN='\033[0;36m'
    _CLR_RESET='\033[0m'
else
    _CLR_BOLD='' _CLR_DIM='' _CLR_GREEN='' _CLR_YELLOW=''
    _CLR_RED='' _CLR_CYAN='' _CLR_RESET=''
fi

# ---------------------------------------------------------------------------
# Minimal logging (used before modules are loaded)
# ---------------------------------------------------------------------------
_pre_log() {
    local level="$1"; shift
    case "$level" in
        OK)   echo -e "${_CLR_GREEN}✓${_CLR_RESET} $*" ;;
        WARN) echo -e "${_CLR_YELLOW}⚠${_CLR_RESET} $*" ;;
        FAIL) echo -e "${_CLR_RED}✗${_CLR_RESET} $*" ;;
        INFO) echo -e "${_CLR_CYAN}$*${_CLR_RESET}" ;;
    esac
}

# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
_on_error() {
    local exit_code=$?
    local line_no="${1:-unknown}"
    if [[ $exit_code -ne 0 && $exit_code -ne 130 ]]; then
        echo "" >&2
        echo -e "${_CLR_RED}ERROR${_CLR_RESET}: Installer failed (exit code ${exit_code}, line ${line_no})" >&2
        echo "Log file: ${INSTALLER_LOG_FILE:-<not initialized>}" >&2
        echo "Report:   https://github.com/adittaya/VPLINK-3.0/issues" >&2
        # Attempt rollback if state module is loaded
        if type rollback_execute &>/dev/null; then
            rollback_execute
        fi
    fi
}

# trap '_on_error $LINENO' ERR

# ---------------------------------------------------------------------------
# Source all core modules
# ---------------------------------------------------------------------------
_load_core_modules() {
    local core_dir="${INSTALLER_DIR}/core"
    local modules=(
        logger.sh
        platform.sh
        state.sh
        config.sh
        packages.sh
        download.sh
        env.sh
        rollback.sh
    )

    for mod in "${modules[@]}"; do
        local path="${core_dir}/${mod}"
        if [[ -f "$path" ]]; then
            # shellcheck source=/dev/null
            source "$path"
        else
            _pre_log WARN "Core module not found: ${mod}"
        fi
    done
}

# ---------------------------------------------------------------------------
# Source platform-specific module
# ---------------------------------------------------------------------------
_load_platform_module() {
    # Ensure platform detection has run
    if type platform_detect_all &>/dev/null; then
        platform_detect_all
    elif type detect_all &>/dev/null; then
        detect_all
    fi

    local plat_dir="${INSTALLER_DIR}/platforms"
    local os="${OS:-unknown}"

    local platform_file=""
    case "$os" in
        linux)  platform_file="${plat_dir}/linux.sh" ;;
        macos)  platform_file="${plat_dir}/macos.sh" ;;
        windows) platform_file="${plat_dir}/windows.sh" ;;
        termux) platform_file="${plat_dir}/termux.sh" ;;
    esac

    if [[ -n "$platform_file" && -f "$platform_file" ]]; then
        # shellcheck source=/dev/null
        source "$platform_file"
    fi

    # Source package definitions
    local pkg_defs="${INSTALLER_DIR}/packages/definitions.sh"
    if [[ -f "$pkg_defs" ]]; then
        # shellcheck source=/dev/null
        source "$pkg_defs"
    fi
}

# ---------------------------------------------------------------------------
# Source interactive UI
# ---------------------------------------------------------------------------
_load_ui() {
    local ui_file="${INSTALLER_DIR}/interactive/ui.sh"
    if [[ -f "$ui_file" ]]; then
        # shellcheck source=/dev/null
        source "$ui_file"
    fi
}

# ---------------------------------------------------------------------------
# Source command modules
# ---------------------------------------------------------------------------
_source_command() {
    local cmd_name="$1"
    local cmd_file=""
    # Check commands/ first, then verification/
    for dir in commands verification; do
        local candidate="${INSTALLER_DIR}/${dir}/${cmd_name}.sh"
        if [[ -f "$candidate" ]]; then
            cmd_file="$candidate"
            break
        fi
    done
    if [[ -n "$cmd_file" ]]; then
        # shellcheck source=/dev/null
        source "$cmd_file"
    else
        echo "ERROR: Command module not found: ${cmd_name}" >&2
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Initialize subsystems
# ---------------------------------------------------------------------------
_init_subsystems() {
    # Initialize logging directory
    if type log_init &>/dev/null; then
        log_init
    fi

    # Initialize state tracking
    if type state_init &>/dev/null; then
        state_init
    fi

    # Initialize config
    if type config_init &>/dev/null; then
        config_init
    fi

    # Initialize rollback tracking
    if type rollback_init &>/dev/null; then
        rollback_init
    fi
}

# ---------------------------------------------------------------------------
# Global flags (set by argument parsing)
# ---------------------------------------------------------------------------
ACTION=""
ACTION_ARGS=()
NONINTERACTIVE=0
DEBUG_MODE=0
DRY_RUN=0
FORCE=0

# ---------------------------------------------------------------------------
# Parse CLI arguments
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            install|update|repair|uninstall|doctor|verify|config|logs|status|version|help)
                ACTION="$1"
                shift
                # Collect remaining args as action args
                ACTION_ARGS=("$@")
                return 0
                ;;
            --noninteractive|-n)
                NONINTERACTIVE=1
                export NONINTERACTIVE=1
                export VPLINK_NONINTERACTIVE=1
                shift
                ;;
            --debug|-d)
                export DEBUG_MODE=1
                export VPLINK_DEBUG=1
                shift
                ;;
            --dry-run)
                export DRY_RUN=1
                export VPLINK_DRY_RUN=1
                shift
                ;;
            --force|-f)
                export FORCE=1
                export VPLINK_FORCE=1
                shift
                ;;
            --no-color)
                NO_COLOR=1
                export NO_COLOR=1
                _CLR_BOLD='' _CLR_DIM='' _CLR_GREEN='' _CLR_YELLOW=''
                _CLR_RED='' _CLR_CYAN='' _CLR_RESET=''
                shift
                ;;
            --version|-V)
                ACTION="version"
                shift
                ;;
            --help|-h)
                ACTION="help"
                shift
                ;;
            -*)
                echo "Unknown option: $1" >&2
                echo "Run '${INSTALLER_NAME} help' for usage." >&2
                exit 1
                ;;
            *)
                # First non-flag arg is the action
                if [[ -z "$ACTION" ]]; then
                    ACTION="$1"
                else
                    ACTION_ARGS+=("$1")
                fi
                shift
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_version() {
    echo "${INSTALLER_NAME} ${INSTALLER_VERSION}"
    echo "Platform: ${OS:-unknown}/${DISTRO_FAMILY:-unknown} ${ARCH:-unknown}"
    if type node &>/dev/null; then
        echo "Node.js:  $(node --version 2>/dev/null || echo 'not found')"
    fi
    echo "Shell:    ${SHELL_TYPE:-unknown}"
    echo "Install dir: ${VPLINK_DIR:-$HOME/vplink3.0}"
}

cmd_help() {
    cat <<EOF
${_CLR_BOLD}${INSTALLER_NAME}${_CLR_RESET} v${INSTALLER_VERSION}

Cross-platform bootstrap installer for VPLink 3.0.

${_CLR_BOLD}USAGE${_CLR_RESET}
    installer <command> [options]

${_CLR_BOLD}COMMANDS${_CLR_RESET}
    install         Full installation (deps + app + config)
    update          Update to latest version
    repair          Fix broken installation
    uninstall       Remove installation completely
    doctor          System diagnostics and health check
    verify          Verify installation integrity
    config <cmd>    Config management (get/set/list/reset)
    logs            View installation logs
    status          Show installation status
    version         Show version info
    help            Show this help message

${_CLR_BOLD}OPTIONS${_CLR_RESET}
    -n, --noninteractive   Skip prompts (use defaults)
    -d, --debug            Enable debug output
    --dry-run              Simulate without making changes
    -f, --force            Force action (skip confirmations)
    --no-color             Disable colored output
    -V, --version          Show version
    -h, --help             Show this help

${_CLR_BOLD}EXAMPLES${_CLR_RESET}
    curl -fsSL https://raw.githubusercontent.com/.../installer.sh | bash -s -- install
    installer install --noninteractive
    installer doctor --debug
    installer config get node_version

${_CLR_BOLD}ENVIRONMENT${_CLR_RESET}
    VPLINK_NONINTERACTIVE=1    Skip all prompts
    VPLINK_DEBUG=1             Enable debug mode
    VPLINK_DIR=/path           Custom install directory
    VPLINK_DRY_RUN=1           Dry-run mode
EOF
}

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------
dispatch() {
    case "${ACTION:-}" in
        install)
            _source_command "install"
            cmd_install "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        update)
            _source_command "update"
            cmd_update "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        repair)
            _source_command "repair"
            cmd_repair "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        uninstall)
            _source_command "uninstall"
            cmd_uninstall "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        doctor)
            _source_command "doctor"
            cmd_doctor "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        verify)
            local verify_file="${INSTALLER_DIR}/verification/verify.sh"
            if [[ -f "$verify_file" ]]; then
                # shellcheck source=/dev/null
                source "$verify_file"
                verify_installation "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            else
                echo "ERROR: verify.sh not found" >&2
                exit 1
            fi
            ;;
        config)
            _source_command "config"
            cmd_config "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        logs)
            _source_command "logs"
            cmd_logs "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        status)
            _source_command "status"
            cmd_status "${ACTION_ARGS[@]+"${ACTION_ARGS[@]}"}"
            ;;
        version)
            cmd_version
            ;;
        help)
            cmd_help
            ;;
        "")
            echo ""
            echo -e "${_CLR_BOLD}${INSTALLER_NAME} v${INSTALLER_VERSION}${_CLR_RESET}"
            echo ""
            echo "No command specified. Available commands:"
            echo ""
            echo "  install      Full installation"
            echo "  update       Update to latest"
            echo "  repair       Fix broken installation"
            echo "  uninstall    Remove installation"
            echo "  doctor       System diagnostics"
            echo "  verify       Verify installation"
            echo "  config       Configuration management"
            echo "  logs         View logs"
            echo "  status       Show status"
            echo "  version      Show version"
            echo "  help         Show help"
            echo ""
            echo "Run '${INSTALLER_NAME} help' for full usage."
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown command: ${ACTION}" >&2
            echo "Run '${INSTALLER_NAME} help' for available commands." >&2
            exit 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    # Parse arguments first (before sourcing modules, for speed on --help/--version)
    parse_args "$@"

    # Special case: --help and --version don't need modules
    if [[ "$ACTION" == "help" ]]; then
        cmd_help
        exit 0
    fi
    if [[ "$ACTION" == "version" ]]; then
        # Need platform detection for version info
        _load_core_modules
        _load_platform_module
        cmd_version
        exit 0
    fi

    # Load all subsystems
    _load_core_modules
    _load_platform_module
    _load_ui
    _init_subsystems

    # Set up error trap now that modules are loaded
    trap '_on_error $LINENO' ERR

    # Log invocation
    if type log_info &>/dev/null; then
        log_info "Installer v${INSTALLER_VERSION} invoked: ${ACTION:-<none>}"
        log_info "Platform: ${OS:-?}/${DISTRO_FAMILY:-?} ${ARCH:-?}"
    fi

    # Dispatch to command
    dispatch
}

# Run main if not being sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
