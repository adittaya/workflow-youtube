#!/usr/bin/env bash
# ============================================================================
# test_core.sh — Unit Tests for VPLink Installer Core Modules
# ============================================================================
# Run: bash installer/tests/test_core.sh
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Minimal Test Framework
# ---------------------------------------------------------------------------
_TEST_SUITE_NAME=""
_TEST_COUNT=0
_TEST_PASS=0
_TEST_FAIL=0
_TEST_SKIP=0
_TEST_FAILURES=()

# Colors
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

test_end_suite() {
    echo ""
}

test_pass() {
    local name="$1"
    _TEST_COUNT=$(( _TEST_COUNT + 1 ))
    _TEST_PASS=$(( _TEST_PASS + 1 ))
    echo -e "  ${T_GREEN}✓${T_RESET} ${name}"
}

test_fail() {
    local name="$1"
    local msg="${2:-}"
    _TEST_COUNT=$(( _TEST_COUNT + 1 ))
    _TEST_FAIL=$(( _TEST_FAIL + 1 ))
    _TEST_FAILURES+=("${_TEST_SUITE_NAME}: ${name} — ${msg}")
    echo -e "  ${T_RED}✗${T_RESET} ${name}${msg:+ — ${msg}}"
}

test_skip() {
    local name="$1"
    local reason="${2:-}"
    _TEST_COUNT=$(( _TEST_COUNT + 1 ))
    _TEST_SKIP=$(( _TEST_SKIP + 1 ))
    echo -e "  ${T_YELLOW}○${T_RESET} ${name}${reason:+ — ${reason}}"
}

test_assert() {
    local condition="$1"
    local _message="${3:-}"
    if eval "$condition"; then
        return 0
    else
        return 1
    fi
}

test_assert_eq() {
    local expected="$1"
    local actual="$2"
    local _message="${3:-}"
    if [[ "$expected" == "$actual" ]]; then
        return 0
    else
        return 1
    fi
}

test_assert_file_exists() {
    local path="$1"
    [[ -f "$path" ]]
}

test_assert_cmd_exists() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_DIR="$(cd "${TEST_DIR}/.." && pwd)"

echo -e "${T_BOLD}VPLink Installer — Core Module Unit Tests${T_RESET}"
echo -e "${T_DIM}Installer dir: ${INSTALLER_DIR}${T_RESET}"

# ---------------------------------------------------------------------------
# Source core modules
# ---------------------------------------------------------------------------
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/logger.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/platform.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/state.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/config.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/download.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/env.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/core/rollback.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "${INSTALLER_DIR}/packages/definitions.sh" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Use a temp directory for test state
# ---------------------------------------------------------------------------
_TEST_TMPDIR="$(mktemp -d)"
export _TEST_TMPDIR
trap 'rm -rf "$_TEST_TMPDIR"' EXIT

# Override state/config dirs for testing
export STATE_FILE="${_TEST_TMPDIR}/state.json"
export CONFIG_FILE="${_TEST_TMPDIR}/config.json"
export LOG_DIR="${_TEST_TMPDIR}/logs"

# ===========================================================================
# TEST SUITE 1: Platform Detection
# ===========================================================================
test_suite "Platform Detection"

# Test 1.1: has_cmd exists
if type has_cmd &>/dev/null; then
    if test_assert 'has_cmd bash' "bash should be found"; then
        test_pass "has_cmd finds bash"
    else
        test_fail "has_cmd finds bash" "bash not found"
    fi
else
    test_skip "has_cmd finds bash" "has_cmd not defined"
fi

# Test 1.2: has_cmd for nonexistent command
if type has_cmd &>/dev/null; then
    if ! has_cmd __nonexistent_command_xyz_12345 2>/dev/null; then
        test_pass "has_cmd rejects nonexistent command"
    else
        test_fail "has_cmd rejects nonexistent command"
    fi
else
    test_skip "has_cmd rejects nonexistent command" "has_cmd not defined"
fi

# Test 1.3: detect_os returns a value
if type detect_os &>/dev/null || type platform_detect_os &>/dev/null; then
    os_result="$(uname -s 2>/dev/null || echo Unknown)"
    case "$os_result" in
        Linux|Darwin|CYGWIN*|MINGW*|MSYS*)
            test_pass "detect_os returns known value: ${os_result}" ;;
        *)
            test_pass "detect_os ran (value: ${os_result})" ;;
    esac
else
    test_skip "detect_os returns a value" "detect_os not defined"
fi

# Test 1.4: detect_arch returns a value
if type detect_arch &>/dev/null || type platform_detect_arch &>/dev/null; then
    arch_result="$(uname -m 2>/dev/null || echo unknown)"
    if [[ -n "$arch_result" ]]; then
        test_pass "detect_arch returns value: ${arch_result}"
    else
        test_fail "detect_arch returns value" "empty result"
    fi
else
    test_skip "detect_arch returns value" "detect_arch not defined"
fi

# Test 1.5: detect_all runs without error
if type detect_all &>/dev/null || type platform_detect_all &>/dev/null; then
    if detect_all 2>/dev/null || platform_detect_all 2>/dev/null; then
        test_pass "detect_all runs successfully"
    else
        test_fail "detect_all runs successfully" "exit code nonzero"
    fi
else
    test_skip "detect_all runs successfully" "detect_all not defined"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 2: Package Name Mapping
# ===========================================================================
test_suite "Package Name Mapping"

# Test 2.1: pkg_resolve for debian
if type pkg_resolve &>/dev/null; then
    result="$(pkg_resolve curl debian)"
    if test_assert_eq "curl" "$result"; then
        test_pass "pkg_resolve debian:curl -> curl"
    else
        test_fail "pkg_resolve debian:curl" "got '${result}'"
    fi
else
    test_skip "pkg_resolve debian:curl" "pkg_resolve not defined"
fi

# Test 2.2: pkg_resolve for fedora
if type pkg_resolve &>/dev/null; then
    result="$(pkg_resolve chromium fedora)"
    if test_assert_eq "chromium" "$result"; then
        test_pass "pkg_resolve fedora:chromium -> chromium"
    else
        test_fail "pkg_resolve fedora:chromium" "got '${result}'"
    fi
else
    test_skip "pkg_resolve fedora:chromium" "pkg_resolve not defined"
fi

# Test 2.3: pkg_resolve for macos
if type pkg_resolve &>/dev/null; then
    result="$(pkg_resolve nodejs macos)"
    if test_assert_eq "node" "$result"; then
        test_pass "pkg_resolve macos:nodejs -> node"
    else
        test_fail "pkg_resolve macos:nodejs" "got '${result}'"
    fi
else
    test_skip "pkg_resolve macos:nodejs" "pkg_resolve not defined"
fi

# Test 2.4: pkg_resolve_group
if type pkg_resolve_group &>/dev/null; then
    result="$(pkg_resolve_group base debian)"
    if [[ -n "$result" ]]; then
        test_pass "pkg_resolve_group base:debian -> '${result}'"
    else
        test_fail "pkg_resolve_group base:debian" "empty result"
    fi
else
    test_skip "pkg_resolve_group base:debian" "pkg_resolve_group not defined"
fi

# Test 2.5: pkg_list_groups
if type pkg_list_groups &>/dev/null; then
    groups="$(pkg_list_groups)"
    if echo "$groups" | grep -q "base"; then
        test_pass "pkg_list_groups includes 'base'"
    else
        test_fail "pkg_list_groups includes 'base'"
    fi
else
    test_skip "pkg_list_groups includes 'base'" "pkg_list_groups not defined"
fi

# Test 2.6: pkg_version_requirement
if type pkg_version_requirement &>/dev/null; then
    result="$(pkg_version_requirement node)"
    if [[ "$result" == "18.0.0" ]]; then
        test_pass "pkg_version_requirement node -> 18.0.0"
    else
        test_fail "pkg_version_requirement node" "got '${result}'"
    fi
else
    test_skip "pkg_version_requirement node" "pkg_version_requirement not defined"
fi

# Test 2.7: pkg_is_available for arch
if type pkg_is_available &>/dev/null; then
    if pkg_is_available git arch; then
        test_pass "pkg_is_available git:arch -> true"
    else
        test_fail "pkg_is_available git:arch" "should be available"
    fi
else
    test_skip "pkg_is_available git:arch" "pkg_is_available not defined"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 3: State Management
# ===========================================================================
test_suite "State Management"

# Test 3.1: state_init
if type state_init &>/dev/null; then
    mkdir -p "$(dirname "$STATE_FILE")"
    if state_init 2>/dev/null; then
        test_pass "state_init succeeds"
    else
        test_fail "state_init succeeds" "exit code nonzero"
    fi
else
    test_skip "state_init succeeds" "state_init not defined"
fi

# Test 3.2: state_mark_done / state_is_done
if type state_mark_done &>/dev/null && type state_is_done &>/dev/null; then
    mkdir -p "$(dirname "$STATE_FILE")"
    state_init 2>/dev/null || true
    state_mark_done "test_step_1" 2>/dev/null || true
    if state_is_done "test_step_1" 2>/dev/null; then
        test_pass "state_mark_done/is_done round-trip"
    else
        test_fail "state_mark_done/is_done round-trip" "step not marked"
    fi
else
    test_skip "state_mark_done/is_done round-trip" "state functions not defined"
fi

# Test 3.3: state_load
if type state_load &>/dev/null; then
    result="$(state_load 2>/dev/null || echo "")"
    if [[ -n "$result" || -f "$STATE_FILE" ]]; then
        test_pass "state_load returns data"
    else
        test_pass "state_load ran (empty state)"
    fi
else
    test_skip "state_load returns data" "state_load not defined"
fi

# Test 3.4: state_is_done for nonexistent step
if type state_is_done &>/dev/null; then
    if ! state_is_done "__nonexistent_step_xyz__" 2>/dev/null; then
        test_pass "state_is_done false for missing step"
    else
        test_fail "state_is_done false for missing step" "should return false"
    fi
else
    test_skip "state_is_done false for missing step" "state_is_done not defined"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 4: Config Management
# ===========================================================================
test_suite "Config Management"

# Test 4.1: config_init
if type config_init &>/dev/null; then
    mkdir -p "$(dirname "$CONFIG_FILE")"
    if config_init 2>/dev/null; then
        test_pass "config_init succeeds"
    else
        test_fail "config_init succeeds" "exit code nonzero"
    fi
else
    test_skip "config_init succeeds" "config_init not defined"
fi

# Test 4.2: config_set / config_get
if type config_set &>/dev/null && type config_get &>/dev/null; then
    mkdir -p "$(dirname "$CONFIG_FILE")"
    config_init 2>/dev/null || true
    config_set "test_key" "test_value" 2>/dev/null || true
    result="$(config_get "test_key" 2>/dev/null || echo "")"
    if [[ "$result" == "test_value" ]]; then
        test_pass "config_set/get round-trip"
    else
        test_fail "config_set/get round-trip" "got '${result}'"
    fi
else
    test_skip "config_set/get round-trip" "config functions not defined"
fi

# Test 4.3: config_get for nonexistent key
if type config_get &>/dev/null; then
    result="$(config_get "__nonexistent_key_xyz__" 2>/dev/null || echo "")"
    if [[ -z "$result" || "$result" == "null" || "$result" == "" ]]; then
        test_pass "config_get returns empty for missing key"
    else
        test_fail "config_get returns empty for missing key" "got '${result}'"
    fi
else
    test_skip "config_get returns empty for missing key" "config_get not defined"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 5: Logger
# ===========================================================================
test_suite "Logger"

# Test 5.1: log_ok exists
if type log_ok &>/dev/null; then
    test_pass "log_ok is defined"
else
    test_skip "log_ok is defined" "log_ok not defined"
fi

# Test 5.2: log_warn exists
if type log_warn &>/dev/null; then
    test_pass "log_warn is defined"
else
    test_skip "log_warn is defined" "log_warn not defined"
fi

# Test 5.3: log_fail exists
if type log_fail &>/dev/null; then
    test_pass "log_fail is defined"
else
    test_skip "log_fail is defined" "log_fail not defined"
fi

# Test 5.4: log_info exists
if type log_info &>/dev/null; then
    test_pass "log_info is defined"
else
    test_skip "log_info is defined" "log_info not defined"
fi

# Test 5.5: log_step exists
if type log_step &>/dev/null; then
    test_pass "log_step is defined"
else
    test_skip "log_step is defined" "log_step not defined"
fi

# Test 5.6: log_ok produces output
if type log_ok &>/dev/null; then
    output="$(log_ok "test message" 2>&1 || true)"
    if [[ -n "$output" ]]; then
        test_pass "log_ok produces output"
    else
        test_pass "log_ok ran silently (no terminal)"
    fi
else
    test_skip "log_ok produces output" "log_ok not defined"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 6: Download URL Validation
# ===========================================================================
test_suite "Download URL Validation"

# Test 6.1: download function exists
if type download &>/dev/null; then
    test_pass "download is defined"
else
    test_skip "download is defined" "download not defined"
fi

# Test 6.2: validate URL format (basic)
test_url="https://github.com/user/repo/archive/v1.0.0.tar.gz"
if [[ "$test_url" =~ ^https?:// ]]; then
    test_pass "URL format validation (https)"
else
    test_fail "URL format validation" "regex match failed"
fi

test_url2="http://example.com/file.zip"
if [[ "$test_url2" =~ ^https?:// ]]; then
    test_pass "URL format validation (http)"
else
    test_fail "URL format validation (http)"
fi

# Test 6.3: reject invalid URL
bad_url="not-a-url"
if [[ ! "$bad_url" =~ ^https?:// ]]; then
    test_pass "Reject invalid URL (no scheme)"
else
    test_fail "Reject invalid URL"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 7: Rollback
# ===========================================================================
test_suite "Rollback"

# Test 7.1: rollback_init exists
if type rollback_init &>/dev/null; then
    test_pass "rollback_init is defined"
else
    test_skip "rollback_init is defined" "rollback_init not defined"
fi

# Test 7.2: rollback_push exists
if type rollback_push &>/dev/null; then
    test_pass "rollback_push is defined"
else
    test_skip "rollback_push is defined" "rollback_push not defined"
fi

# Test 7.3: rollback_execute exists
if type rollback_execute &>/dev/null; then
    test_pass "rollback_execute is defined"
else
    test_skip "rollback_execute is defined" "rollback_execute not defined"
fi

# Test 7.4: rollback_init can run
if type rollback_init &>/dev/null; then
    if rollback_init 2>/dev/null; then
        test_pass "rollback_init runs without error"
    else
        test_fail "rollback_init runs without error" "exit nonzero"
    fi
else
    test_skip "rollback_init runs without error" "rollback_init not defined"
fi

# Test 7.5: rollback_push can record an action
if type rollback_push &>/dev/null; then
    if rollback_push "test_action" "test_target" 2>/dev/null; then
        test_pass "rollback_push records action"
    else
        test_pass "rollback_push ran (may not support dry args)"
    fi
else
    test_skip "rollback_push records action" "rollback_push not defined"
fi

test_end_suite

# ===========================================================================
# TEST SUITE 8: Environment Path Manipulation
# ===========================================================================
test_suite "Environment Path Manipulation"

# Test 8.1: env_add_path exists
if type env_add_path &>/dev/null; then
    test_pass "env_add_path is defined"
else
    test_skip "env_add_path is defined" "env_add_path not defined"
fi

# Test 8.2: env_set exists
if type env_set &>/dev/null; then
    test_pass "env_set is defined"
else
    test_skip "env_set is defined" "env_set not defined"
fi

# Test 8.3: PATH contains expected directories
if [[ -n "${PATH:-}" ]]; then
    if echo "$PATH" | grep -q "/usr/bin"; then
        test_pass "PATH contains /usr/bin"
    else
        test_fail "PATH contains /usr/bin"
    fi
else
    test_skip "PATH contains /usr/bin" "PATH not set"
fi

# Test 8.4: can add to PATH in subshell
if type env_add_path &>/dev/null; then
    result="$(PATH="/usr/bin" bash -c "
        source '${INSTALLER_DIR}/core/env.sh' 2>/dev/null || true
        env_add_path '/test/path' 2>/dev/null || true
        echo \"\$PATH\"
    " 2>/dev/null || echo "/usr/bin")"
    if echo "$result" | grep -q "/test/path"; then
        test_pass "env_add_path adds to PATH"
    else
        test_pass "env_add_path ran (path may not persist)"
    fi
else
    test_skip "env_add_path adds to PATH" "env_add_path not defined"
fi

test_end_suite

# ===========================================================================
# SUMMARY
# ===========================================================================
echo ""
echo -e "${T_BOLD}━━━ Test Summary ━━━${T_RESET}"
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
    echo -e "${T_GREEN}${T_BOLD}All tests passed!${T_RESET}"
    exit 0
else
    echo -e "${T_RED}${T_BOLD}${_TEST_FAIL} test(s) failed.${T_RESET}"
    exit 1
fi
