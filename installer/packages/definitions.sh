#!/usr/bin/env bash
# ============================================================================
# definitions.sh — Cross-Platform Package Name Mapping Tables
# ============================================================================
# Maps generic package names to platform-specific package names.
# Supports: debian, fedora, arch, suse, alpine, macos (homebrew), termux,
#           and windows (MSYS2/pacman).
# ============================================================================

# Prevent double-sourcing
[[ -n "${_PKG_DEFS_LOADED:-}" ]] && return 0
_PKG_DEFS_LOADED=1

# ---------------------------------------------------------------------------
# Version requirements (minimum versions)
# ---------------------------------------------------------------------------
declare -A PKG_VERSION_REQUIREMENTS=(
    [git]=""
    [node]="18.0.0"
    [npm]=""
    [chromium]=""
    [python3]="3.8.0"
)

# ---------------------------------------------------------------------------
# Package group definitions
# Each group maps to an array of generic package names.
# ---------------------------------------------------------------------------
declare -A PKG_GROUP_MEMBERS=(
    [base]="curl git wget jq unzip ca-certificates"
    [build]="build-essential gcc g++ make"
    [browser]="chromium"
    [desktop]="xvfb x11vnc"
    [node]="nodejs npm"
    [python]="python3 pip3"
)

# ---------------------------------------------------------------------------
# Platform-specific package name mappings
# Structure: PKG_MAP[platform:generic_name]=platform_package_name
# ---------------------------------------------------------------------------
declare -A PKG_MAP=()

# --- DEBIAN / UBUNTU ---
PKG_MAP[debian:curl]="curl"
PKG_MAP[debian:git]="git"
PKG_MAP[debian:wget]="wget"
PKG_MAP[debian:jq]="jq"
PKG_MAP[debian:unzip]="unzip"
PKG_MAP[debian:ca-certificates]="ca-certificates"
PKG_MAP[debian:build-essential]="build-essential"
PKG_MAP[debian:gcc]="gcc"
PKG_MAP[debian:g++]="g++"
PKG_MAP[debian:make]="make"
PKG_MAP[debian:chromium]="chromium-browser"
PKG_MAP[debian:xvfb]="xvfb"
PKG_MAP[debian:x11vnc]="x11vnc"
PKG_MAP[debian:nodejs]="nodejs"
PKG_MAP[debian:npm]="npm"
PKG_MAP[debian:python3]="python3"
PKG_MAP[debian:pip3]="python3-pip"

# --- FEDORA / RHEL / CENTOS ---
PKG_MAP[fedora:curl]="curl"
PKG_MAP[fedora:git]="git"
PKG_MAP[fedora:wget]="wget"
PKG_MAP[fedora:jq]="jq"
PKG_MAP[fedora:unzip]="unzip"
PKG_MAP[fedora:ca-certificates]="ca-certificates"
PKG_MAP[fedora:build-essential]="gcc-c++ make"
PKG_MAP[fedora:gcc]="gcc"
PKG_MAP[fedora:g++]="gcc-c++"
PKG_MAP[fedora:make]="make"
PKG_MAP[fedora:chromium]="chromium"
PKG_MAP[fedora:xvfb]="xorg-x11-server-Xvfb"
PKG_MAP[fedora:x11vnc]="x11vnc"
PKG_MAP[fedora:nodejs]="nodejs"
PKG_MAP[fedora:npm]="npm"
PKG_MAP[fedora:python3]="python3"
PKG_MAP[fedora:pip3]="python3-pip"

# --- ARCH / MANJARO ---
PKG_MAP[arch:curl]="curl"
PKG_MAP[arch:git]="git"
PKG_MAP[arch:wget]="wget"
PKG_MAP[arch:jq]="jq"
PKG_MAP[arch:unzip]="unzip"
PKG_MAP[arch:ca-certificates]="ca-certificates"
PKG_MAP[arch:build-essential]="base-devel"
PKG_MAP[arch:gcc]="gcc"
PKG_MAP[arch:g++]="gcc"
PKG_MAP[arch:make]="make"
PKG_MAP[arch:chromium]="chromium"
PKG_MAP[arch:xvfb]="xorg-server-xvfb"
PKG_MAP[arch:x11vnc]="x11vnc"
PKG_MAP[arch:nodejs]="nodejs"
PKG_MAP[arch:npm]="npm"
PKG_MAP[arch:python3]="python"
PKG_MAP[arch:pip3]="python-pip"

# --- SUSE / OPENSUSE ---
PKG_MAP[suse:curl]="curl"
PKG_MAP[suse:git]="git"
PKG_MAP[suse:wget]="wget"
PKG_MAP[suse:jq]="jq"
PKG_MAP[suse:unzip]="unzip"
PKG_MAP[suse:ca-certificates]="ca-certificates"
PKG_MAP[suse:build-essential]="patterns-devel-base-devel_basis"
PKG_MAP[suse:gcc]="gcc"
PKG_MAP[suse:g++]="gcc-c++"
PKG_MAP[suse:make]="make"
PKG_MAP[suse:chromium]="chromium"
PKG_MAP[suse:xvfb]="xorg-x11-server"
PKG_MAP[suse:x11vnc]="x11vnc"
PKG_MAP[suse:nodejs]="nodejs18"
PKG_MAP[suse:npm]="npm18"
PKG_MAP[suse:python3]="python3"
PKG_MAP[suse:pip3]="python3-pip"

# --- ALPINE ---
PKG_MAP[alpine:curl]="curl"
PKG_MAP[alpine:git]="git"
PKG_MAP[alpine:wget]="wget"
PKG_MAP[alpine:jq]="jq"
PKG_MAP[alpine:unzip]="unzip"
PKG_MAP[alpine:ca-certificates]="ca-certificates"
PKG_MAP[alpine:build-essential]="build-base"
PKG_MAP[alpine:gcc]="gcc"
PKG_MAP[alpine:g++]="g++"
PKG_MAP[alpine:make]="make"
PKG_MAP[alpine:chromium]="chromium"
PKG_MAP[alpine:xvfb]="xvfb-run"
PKG_MAP[alpine:x11vnc]="x11vnc"
PKG_MAP[alpine:nodejs]="nodejs"
PKG_MAP[alpine:npm]="npm"
PKG_MAP[alpine:python3]="python3"
PKG_MAP[alpine:pip3]="py3-pip"

# --- MACOS (Homebrew) ---
PKG_MAP[macos:curl]="curl"
PKG_MAP[macos:git]="git"
PKG_MAP[macos:wget]="wget"
PKG_MAP[macos:jq]="jq"
PKG_MAP[macos:unzip]="unzip"
PKG_MAP[macos:ca-certificates]="ca-certificates"
PKG_MAP[macos:build-essential]=""
PKG_MAP[macos:gcc]="gcc"
PKG_MAP[macos:g++]="gcc"
PKG_MAP[macos:make]="make"
PKG_MAP[macos:chromium]="chromium"
PKG_MAP[macos:xvfb]="xquartz"
PKG_MAP[macos:x11vnc]="x11vnc"
PKG_MAP[macos:nodejs]="node"
PKG_MAP[macos:npm]="npm"
PKG_MAP[macos:python3]="python3"
PKG_MAP[macos:pip3]="pipx"

# --- TERMUX ---
PKG_MAP[termux:curl]="curl"
PKG_MAP[termux:git]="git"
PKG_MAP[termux:wget]="wget"
PKG_MAP[termux:jq]="jq"
PKG_MAP[termux:unzip]="unzip"
PKG_MAP[termux:ca-certificates]="ca-certificates"
PKG_MAP[termux:build-essential]=""
PKG_MAP[termux:gcc]="clang"
PKG_MAP[termux:g++]="clang"
PKG_MAP[termux:make]="make"
PKG_MAP[termux:chromium]="chromium"
PKG_MAP[termux:xvfb]="xvfb"
PKG_MAP[termux:x11vnc]="x11vnc"
PKG_MAP[termux:nodejs]="nodejs"
PKG_MAP[termux:npm]="npm"
PKG_MAP[termux:python3]="python"
PKG_MAP[termux:pip3]="pip"

# --- WINDOWS (MSYS2) ---
PKG_MAP[windows:curl]="curl"
PKG_MAP[windows:git]="git"
PKG_MAP[windows:wget]="wget"
PKG_MAP[windows:jq]="jq"
PKG_MAP[windows:unzip]="unzip"
PKG_MAP[windows:ca-certificates]="ca-certificates"
PKG_MAP[windows:build-essential]=""
PKG_MAP[windows:gcc]="gcc"
PKG_MAP[windows:g++]="gcc"
PKG_MAP[windows:make]="make"
PKG_MAP[windows:chromium]="chromium"
PKG_MAP[windows:xvfb]=""
PKG_MAP[windows:x11vnc]=""
PKG_MAP[windows:nodejs]="nodejs"
PKG_MAP[windows:npm]="npm"
PKG_MAP[windows:python3]="python"
PKG_MAP[windows:pip3]="python-pip"

# ---------------------------------------------------------------------------
# Lookup functions
# ---------------------------------------------------------------------------

# pkg_resolve <generic_name> [platform]
# Returns the platform-specific package name for a generic package.
# If platform is not specified, uses the detected DISTRO_FAMILY or OS.
pkg_resolve() {
    local generic="$1"
    local platform="${2:-}"

    # Determine lookup platform: explicit arg > DISTRO_FAMILY > OS
    local lookup_platform="${platform:-${DISTRO_FAMILY:-${OS:-linux}}}"

    local result="${PKG_MAP[${lookup_platform}:${generic}]:-}"

    # If not found, try fallback chain: platform -> DISTRO_FAMILY -> OS
    if [[ -z "$result" && -n "$platform" ]]; then
        local fallback="${DISTRO_FAMILY:-}"
        if [[ -n "$fallback" && "$fallback" != "$lookup_platform" ]]; then
            result="${PKG_MAP[${fallback}:${generic}]:-}"
        fi
    fi
    if [[ -z "$result" ]]; then
        local os_fallback="${OS:-linux}"
        if [[ "$os_fallback" != "$lookup_platform" ]]; then
            result="${PKG_MAP[${os_fallback}:${generic}]:-}"
        fi
    fi

    # If still not found, return the generic name as-is
    if [[ -z "$result" ]]; then
        result="$generic"
    fi

    echo "$result"
}

# pkg_resolve_group <group_name> [platform]
# Returns space-separated list of platform-specific package names for a group.
pkg_resolve_group() {
    local group="$1"
    local platform="${2:-${OS:-linux}}"
    local members="${PKG_GROUP_MEMBERS[$group]:-}"

    if [[ -z "$members" ]]; then
        echo ""
        return 1
    fi

    local result=""
    for generic in $members; do
        local resolved
        resolved="$(pkg_resolve "$generic" "$platform")"
        if [[ -n "$resolved" ]]; then
            result="${result:+$result }$resolved"
        fi
    done

    echo "$result"
}

# pkg_version_requirement <generic_name>
# Returns the minimum version requirement, or empty string if none.
pkg_version_requirement() {
    local generic="$1"
    echo "${PKG_VERSION_REQUIREMENTS[$generic]:-}"
}

# pkg_is_available <generic_name> [platform]
# Returns 0 if the package has a known mapping for the platform.
pkg_is_available() {
    local generic="$1"
    local platform="${2:-${OS:-linux}}"

    local lookup_platform="$platform"
    case "${DISTRO_FAMILY:-$platform}" in
        debian|fedora|arch|suse|alpine|macos|termux|windows)
            lookup_platform="${DISTRO_FAMILY:-$platform}"
            ;;
    esac

    local key="${lookup_platform}:${generic}"
    [[ -n "${PKG_MAP[$key]:-}" ]]
}

# pkg_list_groups
# Prints all available group names.
pkg_list_groups() {
    local group
    for group in "${!PKG_GROUP_MEMBERS[@]}"; do
        echo "$group"
    done
}

# pkg_list_group_packages <group_name>
# Lists the generic package names in a group.
pkg_list_group_packages() {
    echo "${PKG_GROUP_MEMBERS[$1]:-}"
}
