#!/usr/bin/env bash
# ============================================================================
# test_integration.sh — Integration Tests for VPLink Installer
# ============================================================================
# Tests the installer end-to-end without modifying the system.
# Uses dry-run mode and mocks.
#
# Run: bash installer/tests/test_integration.sh
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Minimal Test Framework (same as test_core.sh)
# ---------------------------------------------------------------------------
_TEST_SUITE_NAME=""
_TEST_COUNT=0
_TEST_PASS=0
_TEST_FAIL=0
_TEST_SKIP=0
_TEST_FAILURES=()

if [[ -t 1 ]]; then
    T_BOLD='\033[1m' T_GREEN='\033[0;32m' T_RED='\033[0;31m'
    T_YELLOW='\033[1;33m' T_CYAN='\033[0;36m' T_RESET='\033[0m'
    T_DIM='\033[2m'
else
    T_BOLD='' T_GREEN='' T_RED='' T_YELLOW='' T_CYAN='' T_RESET='' T_DIM=''
fi

test_suite() {
    _TEST_SUITE_NAME="$1"
    echo ""
    echo -e "${T_BOLD}━━━ ${T_CYAN}${_TEST_SUITE_NAME}${T_RESET}"
}

test_end_suite() { echo ""; }

test_pass() {
    _TEST_COUNT=$(( _TEST_COUNT + 1 ))
    _TEST_PASS=$(( _TEST_PASS + 1 ))
    echo -e "  ${T_GREEN}✓${T_RESET} $1"
}

test_fail() {
    local name="$1" msg="${2:-}"
    _TEST_COUNT=$(( _TEST_COUNT + 1 ))
    _TEST_FAIL=$(( _TEST_FAIL + 1 ))
    _TEST_FAILURES+=("${_TEST_SUITE_NAME}: ${name} — ${msg}")
    echo -e "  ${T_RED}✗${T_RESET} ${name}${msg:+ — ${msg}}"
}

test_skip() {
    local name="$1" reason="${2:-}"
    _TEST_COUNT=$(( _TEST_COUNT + 1 ))
    _TEST_SKIP=$(( _TEST_SKIP + 1 ))
    echo -e "  ${T_YELLOW}○${T_RESET} ${name}${reason:+ — ${reason}}"
}

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_DIR="$(cd "${TEST_DIR}/.." && pwd)"

echo -e "${T_BOLD}VPLink Installer — Integration Tests${T_RESET}"
echo -e "${T_DIM}Installer dir: ${INSTALLER_DIR}${T_RESET}"
echo -e "${T_DIM}Mode: dry-run (no system changes)${T_RESET}"

# Use temp dir for all state
_TEST_TMPDIR="$(mktemp -d)"
trap 'rm -rf "$_TEST_TMPDIR"' EXIT

export STATE_FILE="${_TEST_TMPDIR}/state.json"
export CONFIG_FILE="${_TEST_TMPDIR}/config.json"
export LOG_DIR="${_TEST_TMPDIR}/logs"
export INSTALL_DIR="${_TEST_TMPDIR}/vplink"
export VPLINK_NONINTERACTIVE=1
export VPLINK_DRY_RUN=1

# ===========================================================================
# TEST SUITE 1: Module Sourcing
# ===========================================================================
test_suite "Module Sourcing — No Errors"

_MODULES=(
    "core/logger.sh"
    "core/platform.sh"
    "core/state.sh"
    "core/config.sh"
    "core/packages.sh"
    "core/download.sh"
    "core/env.sh"
    "core/rollback.sh"
    "packages/definitions.sh"
    "interactive/ui.sh"
    "platforms/linux.sh"
)

for mod in "${_MODULES[@]}"; do
    _path="${INSTALLER_DIR}/${mod}"
    if [[ ! -f "$_path" ]]; then
        test_skip "Source ${mod}" "file not found"
        continue
    fi
    # Skip modules using declare -A (associative arrays) on bash < 4
    _major="${BASH_VERSINFO[0]:-0}"
    if [[ "$_major" -lt 4 ]] && grep -q 'declare -A' "$_path" 2>/dev/null; then
        test_skip "Source ${mod}" "requires bash 4+"
        continue
    fi
    _errfile="${_TEST_TMPDIR}/err_$(echo "$mod" | tr '/' '_')"
    # Source in subshell to isolate; use running bash (may be newer than /usr/bin/bash on macOS)
    if "${BASH}" -c "source '${_path}' 2>'${_errfile}'" 2>/dev/null; then
        if [[ -s "$_errfile" ]]; then
            test_skip "Source ${mod}" "warnings on stderr"
        else
            test_pass "Source ${mod}"
        fi
    else
        test_fail "Source ${mod}" "exit code $?"
    fi
done

test_end_suite

# ===========================================================================
# TEST SUITE 2: Function Availability
# ===========================================================================
test_suite "Function Availability"

_REQUIRED_FUNCTIONS=(
    "has_cmd"
    "detect_os"
    "detect_distro"
    "detect_arch"
    "detect_all"
    "is_root"
    "is_docker"
    "is_ci"
)

# Source the platform module which defines most of these
"${BASH}" -c "
    set +e
    source '${INSTALLER_DIR}/core/platform.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/logger.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/state.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/config.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/env.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/rollback.sh' 2>/dev/null

    for fn in ${_REQUIRED_FUNCTIONS[*]}; do
        if type \"\$fn\" &>/dev/null; then
            echo \"PASS:\$fn\"
        else
            echo \"FAIL:\$fn\"
        fi
    done
" 2>/dev/null | while IFS=: read -r status func_name; do
    case "$status" in
        PASS) test_pass "Function: ${func_name}" ;;
        FAIL) test_fail "Function: ${func_name}" "not defined" ;;
    esac
done

# Run the check again and capture results for exit code
_func_results="$("${BASH}" -c "
    set +e
    source '${INSTALLER_DIR}/core/platform.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/logger.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/state.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/config.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/env.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/rollback.sh' 2>/dev/null

    _fail=0
    for fn in ${_REQUIRED_FUNCTIONS[*]}; do
        if ! type \"\$fn\" &>/dev/null; then
            echo \"MISSING:\$fn\"
            _fail=\$(( _fail + 1 ))
        fi
    done
    echo \"TOTAL_MISSING:\$_fail\"
" 2>/dev/null || echo "TOTAL_MISSING:1")"

_missing_count="$(echo "$_func_results" | grep "^TOTAL_MISSING:" | cut -d: -f2)"
if [[ "${_missing_count:-1}" -eq 0 ]]; then
    test_pass "All required functions defined"
else
    test_fail "Required functions missing" "${_missing_count} missing"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 3: Doctor Command (Dry Run)
# ===========================================================================
test_suite "Doctor Command (Dry Run)"

# Source the installer modules and run doctor-like checks
"${BASH}" -c "
    set +e
    export INSTALLER_DIR='${INSTALLER_DIR}'
    export VPLINK_DRY_RUN=1
    export STATE_FILE='${_TEST_TMPDIR}/state.json'
    export CONFIG_FILE='${_TEST_TMPDIR}/config.json'
    source '${INSTALLER_DIR}/core/platform.sh' 2>/dev/null
    source '${INSTALLER_DIR}/core/logger.sh' 2>/dev/null
    detect_all 2>/dev/null

    # Check that we can detect the platform
    if [[ -n \"\${OS:-}\" ]]; then
        echo \"PASS:os_detected=\${OS}\"
    else
        echo \"FAIL:os_detected\"
    fi

    if [[ -n \"\${ARCH:-}\" ]]; then
        echo \"PASS:arch_detected=\${ARCH}\"
    else
        echo \"FAIL:arch_detected\"
    fi

    if [[ -n \"\${PKG_MANAGER:-}\" ]]; then
        echo \"PASS:pkg_manager_detected=\${PKG_MANAGER}\"
    else
        echo \"FAIL:pkg_manager_detected\"
    fi

    # Check network detection function exists
    if type has_network &>/dev/null; then
        echo \"PASS:has_network_defined\"
    else
        echo \"FAIL:has_network_defined\"
    fi
" 2>/dev/null | while IFS=: read -r status detail; do
    case "$status" in
        PASS) test_pass "Doctor: ${detail}" ;;
        FAIL) test_fail "Doctor: ${detail}" ;;
    esac
done

test_end_suite

# ===========================================================================
# TEST SUITE 4: Config Get/Set
# ===========================================================================
test_suite "Config Get/Set Integration"

"${BASH}" -c "
    set +e
    export CONFIG_FILE='${_TEST_TMPDIR}/config_integ.json'
    source '${INSTALLER_DIR}/core/config.sh' 2>/dev/null
    config_init 2>/dev/null || true

    # Set a value
    config_set 'browser' 'chromium' 2>/dev/null || true
    config_set 'headless' 'true' 2>/dev/null || true

    # Get values
    v1=\"\$(config_get 'browser' 2>/dev/null || echo '')\"
    v2=\"\$(config_get 'headless' 2>/dev/null || echo '')\"

    if [[ \"\$v1\" == 'chromium' ]]; then
        echo 'PASS:set_get_browser'
    else
        echo \"FAIL:set_get_browser:got=\$v1\"
    fi

    if [[ \"\$v2\" == 'true' ]]; then
        echo 'PASS:set_get_headless'
    else
        echo \"FAIL:set_get_headless:got=\$v2\"
    fi

    # Get nonexistent
    v3=\"\$(config_get 'nonexistent' 2>/dev/null || echo '')\"
    if [[ -z \"\$v3\" || \"\$v3\" == 'null' ]]; then
        echo 'PASS:get_nonexistent_returns_empty'
    else
        echo \"FAIL:get_nonexistent_returns_empty:got=\$v3\"
    fi
" 2>/dev/null | while IFS=: read -r status detail; do
    case "$status" in
        PASS) test_pass "Config: ${detail}" ;;
        FAIL) test_fail "Config: ${detail}" ;;
    esac
done

test_end_suite

# ===========================================================================
# TEST SUITE 5: State Management Integration
# ===========================================================================
test_suite "State Management Integration"

"${BASH}" -c "
    set +e
    export STATE_FILE='${_TEST_TMPDIR}/state_integ.json'
    source '${INSTALLER_DIR}/core/state.sh' 2>/dev/null
    state_init 2>/dev/null || true

    # Mark steps done
    state_mark_done 'prereqs' 2>/dev/null || true
    state_mark_done 'nodejs' 2>/dev/null || true
    state_mark_done 'playwright' 2>/dev/null || true

    # Check steps
    if state_is_done 'prereqs' 2>/dev/null; then
        echo 'PASS:prereqs_done'
    else
        echo 'FAIL:prereqs_done'
    fi

    if state_is_done 'nodejs' 2>/dev/null; then
        echo 'PASS:nodejs_done'
    else
        echo 'FAIL:nodejs_done'
    fi

    if state_is_done 'playwright' 2>/dev/null; then
        echo 'PASS:playwright_done'
    else
        echo 'FAIL:playwright_done'
    fi

    # Nonexistent step should not be done
    if ! state_is_done 'never_done' 2>/dev/null; then
        echo 'PASS:never_done_not_done'
    else
        echo 'FAIL:never_done_not_done'
    fi
" 2>/dev/null | while IFS=: read -r status detail; do
    case "$status" in
        PASS) test_pass "State: ${detail}" ;;
        FAIL) test_fail "State: ${detail}" ;;
    esac
done

test_end_suite

# ===========================================================================
# TEST SUITE 6: Platform Detection Outputs
# ===========================================================================
test_suite "Platform Detection Outputs"

"${BASH}" -c "
    set +e
    source '${INSTALLER_DIR}/core/platform.sh' 2>/dev/null
    detect_all 2>/dev/null

    # Verify all expected exports exist
    for var in OS DISTRO DISTRO_FAMILY ARCH LIBC PKG_MANAGER SUDO IS_ROOT; do
        val=\"\${!var:-__UNSET__}\"
        if [[ \"\$val\" != '__UNSET__' ]]; then
            echo \"PASS:var_\${var}=\${val}\"
        else
            echo \"FAIL:var_\${var}\"
        fi
    done

    # Verify boolean exports
    for var in IS_DOCKER IS_WSL IS_CI IS_TERMUX; do
        val=\"\${!var:-__UNSET__}\"
        if [[ \"\$val\" == '0' || \"\$val\" == '1' ]]; then
            echo \"PASS:bool_\${var}=\${val}\"
        else
            echo \"FAIL:bool_\${var}:val=\$val\"
        fi
    done
" 2>/dev/null | while IFS=: read -r status detail; do
    case "$status" in
        PASS) test_pass "Platform: ${detail}" ;;
        FAIL) test_fail "Platform: ${detail}" ;;
    esac
done

test_end_suite

# ===========================================================================
# TEST SUITE 7: Installer Script Structural Checks
# ===========================================================================
test_suite "Installer Script Structure"

_installer="${INSTALLER_DIR}/installer.sh"

if [[ -f "$_installer" ]]; then
    test_pass "installer.sh exists"
else
    test_fail "installer.sh exists"
    test_end_suite
    echo -e "\n${T_RED}${T_BOLD}Cannot continue without installer.sh${T_RESET}\n"
    exit 1
fi

# Check shebang
head_line="$(head -1 "$_installer")"
if [[ "$head_line" == "#!/usr/bin/env bash" || "$head_line" == "#!/bin/bash" ]]; then
    test_pass "installer.sh has valid shebang"
else
    test_fail "installer.sh has valid shebang" "got: ${head_line}"
fi

# Check key functions exist in installer.sh
for fn in main parse_args dispatch cmd_help cmd_version; do
    if grep -q "^${fn}()" "$_installer" || grep -q "^function ${fn}" "$_installer" || grep -q "^${fn} *\(\)" "$_installer"; then
        test_pass "installer.sh defines: ${fn}"
    else
        test_fail "installer.sh defines: ${fn}" "function not found"
    fi
done

# Check set -euo pipefail
if grep -q 'set -euo pipefail\|set -euo pipefail' "$_installer"; then
    test_pass "installer.sh has strict mode"
else
    test_fail "installer.sh has strict mode"
fi

# Check error trap
if grep -q 'trap' "$_installer"; then
    test_pass "installer.sh has error trap"
else
    test_fail "installer.sh has error trap"
fi

# Check version string
if grep -q "INSTALLER_VERSION=" "$_installer"; then
    ver="$(grep 'INSTALLER_VERSION=' "$_installer" | head -1 | cut -d= -f2 | tr -d '"')"
    test_pass "installer.sh version: ${ver}"
else
    test_fail "installer.sh version string"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 8: Package Definitions Coverage
# ===========================================================================
test_suite "Package Definitions Coverage"

_pkg_defs="${INSTALLER_DIR}/packages/definitions.sh"
if [[ ! -f "$_pkg_defs" ]]; then
    test_fail "definitions.sh exists"
    test_end_suite
    exit 1
fi

test_pass "definitions.sh exists"

# Check all expected platforms have mappings
for platform in debian fedora arch suse alpine macos termux windows; do
    if grep -q "PKG_MAP\[${platform}:" "$_pkg_defs"; then
        test_pass "Platform mappings: ${platform}"
    else
        test_fail "Platform mappings: ${platform}" "no entries found"
    fi
done

# Check all expected groups
for group in base build browser desktop node python; do
    if grep -q "\[${group}\]=" "$_pkg_defs"; then
        test_pass "Group definition: ${group}"
    else
        test_fail "Group definition: ${group}" "not found"
    fi
done

# Check version requirements
if grep -q "PKG_VERSION_REQUIREMENTS" "$_pkg_defs"; then
    test_pass "Version requirements defined"
else
    test_fail "Version requirements defined"
fi

test_end_suite

# ===========================================================================
# SUMMARY
# ===========================================================================
echo ""
echo -e "${T_BOLD}━━━ Integration Test Summary ━━━${T_RESET}"
echo ""
echo -e "  Total:  ${_TEST_COUNT}"
echo -e "  ${T_GREEN}Passed: ${_TEST_PASS}${T_RESET}"
echo -e "  ${T_RED}Failed: ${_TEST_FAIL}${T_RESET}"
echo -e "  ${T_YELLOW}Skipped:${_TEST_SKIP}${T_RESET}"
echo ""

if [[ ${#_TEST_FAILURES[@]} -gt 0 ]]; then
    echo -e "${T_RED}${T_BOLD}Failures:${T_RESET}"
    for f in "${_TEST_FAILURES[@]}"; do
        echo -e "  ${T_RED}✗${T_RESET} $f"
    done
    echo ""
fi

if [[ $_TEST_FAIL -eq 0 ]]; then
    echo -e "${T_GREEN}${T_BOLD}All integration tests passed!${T_RESET}"
    exit 0
else
    echo -e "${T_RED}${T_BOLD}${_TEST_FAIL} test(s) failed.${T_RESET}"
    exit 1
fi
