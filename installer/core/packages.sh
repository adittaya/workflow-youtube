#!/usr/bin/env bash
# ============================================================================
# packages.sh — Cross-Platform Package Installation Abstraction
# ============================================================================
# Maps generic package names to OS-specific packages and provides a
# unified interface for install/remove/search/update across all distros.
#
# Requires: platform.sh (for PKG_MANAGER, PKG_INSTALL, etc.)
# ============================================================================

[[ -n "${_PACKAGES_LOADED:-}" ]] && return 0
_PACKAGES_LOADED=1

# ---------------------------------------------------------------------------
# Internal: Package name mapping tables
# Maps "generic-name" -> "distro-specific-name"
# Format: _MAP_<FAMILY>_<GENERIC>=<specific>
# ---------------------------------------------------------------------------

# --- Common tools -----------------------------------------------------------
_MAP_DEBIAN_git="git"
_MAP_FEDORA_git="git"
_MAP_ARCH_git="git"
_MAP_SUSE_git="git"
_MAP_ALPINE_git="git"
_MAP_TERMUX_git="git"
_MAP_MACOS_git="git"

_MAP_DEBIAN_curl="curl"
_MAP_FEDORA_curl="curl"
_MAP_ARCH_curl="curl"
_MAP_SUSE_curl="curl"
_MAP_ALPINE_curl="curl"
_MAP_TERMUX_curl="curl"
_MAP_MACOS_curl="curl"

_MAP_DEBIAN_wget="wget"
_MAP_FEDORA_wget="wget"
_MAP_ARCH_wget="wget"
_MAP_SUSE_wget="wget"
_MAP_ALPINE_wget="wget"
_MAP_TERMUX_wget="wget"
_MAP_MACOS_wget="wget"

_MAP_DEBIAN_jq="jq"
_MAP_FEDORA_jq="jq"
_MAP_ARCH_jq="jq"
_MAP_SUSE_jq="jq"
_MAP_ALPINE_jq="jq"
_MAP_TERMUX_jq="jq"
_MAP_MACOS_jq="jq"

_MAP_DEBIAN_unzip="unzip"
_MAP_FEDORA_unzip="unzip"
_MAP_ARCH_unzip="unzip"
_MAP_SUSE_unzip="unzip"
_MAP_ALPINE_unzip="unzip"
_MAP_TERMUX_unzip="unzip"
_MAP_MACOS_unzip="unzip"

_MAP_DEBIAN_xz_utils="xz-utils"
_MAP_FEDORA_xz_utils="xz"
_MAP_ARCH_xz_utils="xz"
_MAP_SUSE_xz_utils="xz"
_MAP_ALPINE_xz_utils="xz"
_MAP_TERMUX_xz_utils="xz"
_MAP_MACOS_xz_utils="xz"

_MAP_DEBIAN_make="make"
_MAP_FEDORA_make="make"
_MAP_ARCH_make="make"
_MAP_SUSE_make="make"
_MAP_ALPINE_make="make"
_MAP_TERMUX_make="make"
_MAP_MACOS_make="make"

_MAP_DEBIAN_gcc="gcc"
_MAP_FEDORA_gcc="gcc"
_MAP_ARCH_gcc="gcc"
_MAP_SUSE_gcc="gcc"
_MAP_ALPINE_gcc="gcc"
_MAP_TERMUX_gcc="clang"
_MAP_MACOS_gcc="gcc"

_MAP_DEBIAN_g__="g++"
_MAP_FEDORA_g__="gcc-c++"
_MAP_ARCH_g__="gcc"
_MAP_SUSE_g__="gcc-c++"
_MAP_ALPINE_g__="g++"
_MAP_TERMUX_g__="clang"
_MAP_MACOS_g__="gcc"

_MAP_DEBIAN_build_essential="build-essential"
_MAP_FEDORA_build_essential="make gcc gcc-c++ kernel-devel"
_MAP_ARCH_build_essential="base-devel"
_MAP_SUSE_build_essential="patterns-devel-base-devel_basis"
_MAP_ALPINE_build_essential="build-base"
_MAP_TERMUX_build_essential="build-essential"
_MAP_MACOS_build_essential=""

_MAP_DEBIAN_python3="python3"
_MAP_FEDORA_python3="python3"
_MAP_ARCH_python3="python"
_MAP_SUSE_python3="python3"
_MAP_ALPINE_python3="python3"
_MAP_TERMUX_python3="python"
_MAP_MACOS_python3="python3"

_MAP_DEBIAN_python3_pip="python3-pip"
_MAP_FEDORA_python3_pip="python3-pip"
_MAP_ARCH_python3_pip="python-pip"
_MAP_SUSE_python3_pip="python3-pip"
_MAP_ALPINE_python3_pip="py3-pip"
_MAP_TERMUX_python3_pip="python"
_MAP_MACOS_python3_pip=""

_MAP_DEBIAN_cmake="cmake"
_MAP_FEDORA_cmake="cmake"
_MAP_ARCH_cmake="cmake"
_MAP_SUSE_cmake="cmake"
_MAP_ALPINE_cmake="cmake"
_MAP_TERMUX_cmake="cmake"
_MAP_MACOS_cmake="cmake"

_MAP_DEBIAN_pkg_config="pkg-config"
_MAP_FEDORA_pkg_config="pkgconf-pkg-config"
_MAP_ARCH_pkg_config="pkgconf"
_MAP_SUSE_pkg_config="pkg-config"
_MAP_ALPINE_pkg_config="pkgconf"
_MAP_TERMUX_pkg_config="pkg-config"
_MAP_MACOS_pkg_config="pkg-config"

_MAP_DEBIAN_certs="ca-certificates"
_MAP_FEDORA_certs="ca-certificates"
_MAP_ARCH_certs="ca-certificates"
_MAP_SUSE_certs="ca-certificates"
_MAP_ALPINE_certs="ca-certificates"
_MAP_TERMUX_certs="ca-certificates"
_MAP_MACOS_certs=""

_MAP_DEBIAN_openssl="libssl-dev"
_MAP_FEDORA_openssl="openssl-devel"
_MAP_ARCH_openssl="openssl"
_MAP_SUSE_openssl="libopenssl-devel"
_MAP_ALPINE_openssl="openssl-dev"
_MAP_TERMUX_openssl="openssl"
_MAP_MACOS_openssl="openssl"

_MAP_DEBIAN_zlib="zlib1g-dev"
_MAP_FEDORA_zlib="zlib-devel"
_MAP_ARCH_zlib="zlib"
_MAP_SUSE_zlib="zlib-devel"
_MAP_ALPINE_zlib="zlib-dev"
_MAP_TERMUX_zlib="zlib"
_MAP_MACOS_zlib="zlib"

_MAP_DEBIAN_nodejs="nodejs"
_MAP_FEDORA_nodejs="nodejs"
_MAP_ARCH_NODEJS="nodejs npm"
_MAP_SUSE_nodejs="nodejs-default-devel"
_MAP_ALPINE_nodejs="nodejs"
_MAP_TERMUX_nodejs="nodejs-lts"
_MAP_MACOS_nodejs="node"

# --- Desktop / Display ------------------------------------------------------
_MAP_DEBIAN_chromium="chromium-browser"
_MAP_FEDORA_chromium="chromium"
_MAP_ARCH_chromium="chromium"
_MAP_SUSE_chromium="chromium"
_MAP_ALPINE_chromium="chromium"
_MAP_TERMUX_chromium="chromium"
_MAP_MACOS_chromium=""

_MAP_DEBIAN_chrome="google-chrome-stable"
_MAP_FEDORA_chrome="google-chrome-stable"
_MAP_ARCH_chrome="google-chrome"
_MAP_SUSE_chrome="google-chrome-stable"
_MAP_ALPINE_chrome=""
_MAP_TERMUX_chrome=""
_MAP_MACOS_chrome=""

_MAP_DEBIAN_xvfb="xvfb"
_MAP_FEDORA_xvfb="xorg-x11-server-Xvfb"
_MAP_ARCH_xvfb="xorg-server-xvfb"
_MAP_SUSE_xvfb="xorg-x11-server"
_MAP_ALPINE_xvfb="xvfb-run"
_MAP_TERMUX_xvfb=""
_MAP_MACOS_xvfb=""

_MAP_DEBIAN_x11vnc="x11vnc"
_MAP_FEDORA_x11vnc="x11vnc"
_MAP_ARCH_x11vnc="x11vnc"
_MAP_SUSE_x11vnc="x11vnc"
_MAP_ALPINE_x11vnc="x11vnc"
_MAP_TERMUX_x11vnc=""
_MAP_MACOS_x11vnc=""

_MAP_DEBIAN_xdg_utils="xdg-utils"
_MAP_FEDORA_xdg_utils="xdg-utils"
_MAP_ARCH_xdg_utils="xdg-utils"
_MAP_SUSE_xdg_utils="xdg-utils"
_MAP_ALPINE_xdg_utils="xdg-utils"
_MAP_TERMUX_xdg_utils=""
_MAP_MACOS_xdg_utils=""

# --- Misc -------------------------------------------------------------------
_MAP_DEBIAN_ripgrep="ripgrep"
_MAP_FEDORA_ripgrep="ripgrep"
_MAP_ARCH_ripgrep="ripgrep"
_MAP_SUSE_ripgrep="ripgrep"
_MAP_ALPINE_ripgrep="ripgrep"
_MAP_TERMUX_ripgrep="ripgrep"
_MAP_MACOS_ripgrep="ripgrep"

_MAP_DEBIAN_tree="tree"
_MAP_FEDORA_tree="tree"
_MAP_ARCH_tree="tree"
_MAP_SUSE_tree="tree"
_MAP_ALPINE_tree="tree"
_MAP_TERMUX_tree="tree"
_MAP_MACOS_tree="tree"

_MAP_DEBIAN_htop="htop"
_MAP_FEDORA_htop="htop"
_MAP_ARCH_htop="htop"
_MAP_SUSE_htop="htop"
_MAP_ALPINE_htop="htop"
_MAP_TERMUX_htop="htop"
_MAP_MACOS_htop="htop"

_MAP_DEBIAN_screen="screen"
_MAP_FEDORA_screen="screen"
_MAP_ARCH_screen="screen"
_MAP_SUSE_screen="screen"
_MAP_ALPINE_screen="screen"
_MAP_TERMUX_screen="screen"
_MAP_MACOS_screen="screen"

_MAP_DEBIAN_tmux="tmux"
_MAP_FEDORA_tmux="tmux"
_MAP_ARCH_tmux="tmux"
_MAP_SUSE_tmux="tmux"
_MAP_ALPINE_tmux="tmux"
_MAP_TERMUX_tmux="tmux"
_MAP_MACOS_tmux="tmux"

_MAP_DEBIAN_file="file"
_MAP_FEDORA_file="file"
_MAP_ARCH_file="file"
_MAP_SUSE_file="file"
_MAP_ALPINE_file="file"
_MAP_TERMUX_file="file"
_MAP_MACOS_file="file"

_MAP_DEBIAN_libxml2="libxml2-dev"
_MAP_FEDORA_libxml2="libxml2-devel"
_MAP_ARCH_libxml2="libxml2"
_MAP_SUSE_libxml2="libxml2-devel"
_MAP_ALPINE_libxml2="libxml2-dev"
_MAP_TERMUX_libxml2="libxml2"
_MAP_MACOS_libxml2="libxml2"

_MAP_DEBIAN_libffi="libffi-dev"
_MAP_FEDORA_libffi="libffi-devel"
_MAP_ARCH_libffi="libffi"
_MAP_SUSE_libffi="libffi-devel"
_MAP_ALPINE_libffi="libffi-dev"
_MAP_TERMUX_libffi="libffi"
_MAP_MACOS_libffi="libffi"

# ---------------------------------------------------------------------------
# Internal: resolve generic name to distro-specific name
# ---------------------------------------------------------------------------
_packages_resolve_name() {
    local generic="$1"
    local family="${DISTRO_FAMILY:-unknown}"
    local family_upper
    family_upper="$(echo "$family" | tr '[:lower:]' '[:upper:]')"

    # Normalize family for macOS
    if [[ "${OS:-}" == "macos" ]]; then
        family="macos"
        family_upper="MACOS"
    fi

    # For termux, try termux first, then fallback to the underlying distro
    if [[ "${IS_TERMUX:-0}" -eq 1 ]]; then
        local varname="_MAP_TERMUX_${generic}"
        local resolved="${!varname:-}"
        if [[ -n "$resolved" ]]; then
            echo "$resolved"
            return 0
        fi
    fi

    # Try family-specific mapping
    local varname="_MAP_${family_upper}_${generic}"
    local resolved="${!varname:-}"

    if [[ -n "$resolved" ]]; then
        echo "$resolved"
        return 0
    fi

    # Try uppercase distro name
    local distro_upper
    distro_upper="$(echo "${DISTRO:-unknown}" | tr '[:lower:]' '[:upper:]')"
    varname="_MAP_${distro_upper}_${generic}"
    resolved="${!varname:-}"

    if [[ -n "$resolved" ]]; then
        echo "$resolved"
        return 0
    fi

    # Fallback: return generic name as-is
    echo "$generic"
    return 0
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# pkg_install — install a generic package
packages_install() { pkg_install "$@"; }
pkg_install() {
    local generic_name="$1"
    local extra_args="${2:-}"

    if [[ -z "$generic_name" ]]; then
        echo "Error: pkg_install requires a package name" >&2
        return 1
    fi

    # Check if already installed
    if pkg_is_installed "$generic_name" 2>/dev/null; then
        echo "Package '$generic_name' is already installed."
        return 0
    fi

    local resolved
    resolved="$(_packages_resolve_name "$generic_name")"

    # Empty resolved means nothing to install on this platform
    if [[ -z "$resolved" ]]; then
        echo "Package '$generic_name' is not available on this platform, skipping."
        return 0
    fi

    # Install each space-separated package
    local pkg
    for pkg in $resolved; do
        if [[ -n "$pkg" ]]; then
            echo "Installing '$pkg'..."
            # shellcheck disable=SC2086
            if ! eval "${PKG_INSTALL:-}" $pkg $extra_args 2>&1; then
                echo "Warning: Failed to install '$pkg'" >&2
            fi
        fi
    done
}

# pkg_update — update package lists
packages_update() { pkg_update; }
pkg_update() {
    if [[ -z "${PKG_UPDATE:-}" ]]; then
        echo "No package manager configured." >&2
        return 1
    fi
    echo "Updating package lists..."
    eval "${PKG_UPDATE}"
}

# pkg_upgrade — upgrade all packages
packages_upgrade() { pkg_upgrade; }
pkg_upgrade() {
    echo "Upgrading all packages..."
    case "${PKG_MANAGER:-}" in
        apt)
            $SUDO apt-get upgrade -y 2>&1 ;;
        dnf)
            $SUDO dnf upgrade -y 2>&1 ;;
        yum)
            $SUDO yum upgrade -y 2>&1 ;;
        pacman)
            $SUDO pacman -Syu --noconfirm 2>&1 ;;
        zypper)
            $SUDO zypper update -y 2>&1 ;;
        apk)
            $SUDO apk upgrade --no-cache 2>&1 ;;
        brew)
            brew upgrade 2>&1 ;;
        pkg)
            $SUDO pkg upgrade -y 2>&1 ;;
        *)
            echo "No upgrade command for package manager: ${PKG_MANAGER:-unknown}" >&2
            return 1
            ;;
    esac
}

# pkg_is_installed — check if a package is installed
packages_is_installed() { pkg_is_installed "$@"; }
pkg_is_installed() {
    local generic_name="$1"
    local resolved
    resolved="$(_packages_resolve_name "$generic_name")"

    # Check each resolved package
    local pkg
    for pkg in $resolved; do
        if [[ -z "$pkg" ]]; then
            continue
        fi
        case "${PKG_MANAGER:-}" in
            apt)
                dpkg -s "$pkg" >/dev/null 2>&1 ;;
            dnf|yum)
                rpm -q "$pkg" >/dev/null 2>&1 ;;
            pacman)
                pacman -Qi "$pkg" >/dev/null 2>&1 ;;
            zypper)
                rpm -q "$pkg" >/dev/null 2>&1 ;;
            apk)
                apk info -e "$pkg" >/dev/null 2>&1 ;;
            brew)
                brew list --formula "$pkg" >/dev/null 2>&1 ;;
            pkg)
                pkg list-installed "$pkg" 2>/dev/null | grep -q "$pkg" ;;
            *)
                has_cmd "$pkg" 2>/dev/null ;;
        esac
        if [[ $? -eq 0 ]]; then
            return 0
        fi
    done
    return 1
}

# pkg_version — get installed version of a package
packages_version() { pkg_version "$@"; }
pkg_version() {
    local generic_name="$1"
    local resolved
    resolved="$(_packages_resolve_name "$generic_name")"

    local pkg
    for pkg in $resolved; do
        if [[ -z "$pkg" ]]; then continue; fi
        case "${PKG_MANAGER:-}" in
            apt)
                dpkg -s "$pkg" 2>/dev/null | awk -F': ' '/^Version:/{print $2}' ;;
            dnf|yum)
                rpm -q --queryformat '%{VERSION}-%{RELEASE}' "$pkg" 2>/dev/null ;;
            pacman)
                pacman -Qi "$pkg" 2>/dev/null | awk -F': ' '/^Version:/{print $2}' ;;
            zypper)
                rpm -q --queryformat '%{VERSION}-%{RELEASE}' "$pkg" 2>/dev/null ;;
            apk)
                apk info -e "$pkg" 2>/dev/null | awk '/[0-9]/{print $1}' ;;
            brew)
                brew list --formula --versions "$pkg" 2>/dev/null | awk '{print $2}' ;;
            *)
                echo "unknown" ;;
        esac
        if [[ $? -eq 0 ]]; then return 0; fi
    done
    return 1
}

# pkg_search — search for a package
packages_search() { pkg_search "$@"; }
pkg_search() {
    local name="$1"
    case "${PKG_MANAGER:-}" in
        apt)     apt-cache search "$name" 2>/dev/null ;;
        dnf)     dnf search "$name" 2>/dev/null ;;
        yum)     yum search "$name" 2>/dev/null ;;
        pacman)  pacman -Ss "$name" 2>/dev/null ;;
        zypper)  zypper search "$name" 2>/dev/null ;;
        apk)     apk search "$name" 2>/dev/null ;;
        brew)    brew search "$name" 2>/dev/null ;;
        pkg)     pkg search "$name" 2>/dev/null ;;
        *)       echo "Search not supported for: ${PKG_MANAGER:-unknown}" >&2; return 1 ;;
    esac
}

# pkg_remove — remove a package
packages_remove() { pkg_remove "$@"; }
pkg_remove() {
    local generic_name="$1"
    local resolved
    resolved="$(_packages_resolve_name "$generic_name")"

    local pkg
    for pkg in $resolved; do
        if [[ -z "$pkg" ]]; then continue; fi
        echo "Removing '$pkg'..."
        case "${PKG_MANAGER:-}" in
            apt)     $SUDO apt-get remove -y "$pkg" 2>&1 ;;
            dnf)     $SUDO dnf remove -y "$pkg" 2>&1 ;;
            yum)     $SUDO yum remove -y "$pkg" 2>&1 ;;
            pacman)  $SUDO pacman -R --noconfirm "$pkg" 2>&1 ;;
            zypper)  $SUDO zypper remove -y "$pkg" 2>&1 ;;
            apk)     $SUDO apk del "$pkg" 2>&1 ;;
            brew)    brew uninstall "$pkg" 2>&1 ;;
            pkg)     $SUDO pkg uninstall -y "$pkg" 2>&1 ;;
            *)       echo "Remove not supported for: ${PKG_MANAGER:-unknown}" >&2; return 1 ;;
        esac
    done
}

# pkg_cleanup — clean package cache
packages_cleanup() { pkg_cleanup; }
pkg_cleanup() {
    echo "Cleaning package cache..."
    case "${PKG_MANAGER:-}" in
        apt)     $SUDO apt-get autoremove -y 2>&1 && $SUDO apt-get clean 2>&1 ;;
        dnf)     $SUDO dnf clean all 2>&1 ;;
        yum)     $SUDO yum clean all 2>&1 ;;
        pacman)  $SUDO pacman -Scc --noconfirm 2>&1 ;;
        zypper)  $SUDO zypper clean --all 2>&1 ;;
        apk)     $SUDO apk cache clean 2>&1 ;;
        brew)    brew cleanup 2>&1 ;;
        pkg)     $SUDO pkg clean -y 2>&1 ;;
        *)       echo "Cleanup not supported for: ${PKG_MANAGER:-unknown}" >&2; return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# System dependency installation
# ---------------------------------------------------------------------------

# pkg_install_system_deps — install common system dependencies
packages_install_system_deps() { pkg_install_system_deps; }
pkg_install_system_deps() {
    local deps=(
        "git"
        "curl"
        "wget"
        "jq"
        "unzip"
        "xz_utils"
        "make"
        "file"
        "certs"
    )

    # Only install build tools on full desktop/server systems
    if [[ "${IS_TERMUX:-0}" -eq 0 ]]; then
        deps+=("build_essential")
    fi

    echo "Installing system dependencies..."
    for dep in "${deps[@]}"; do
        pkg_install "$dep"
    done
}

# pkg_install_display_deps — install display-related dependencies
packages_install_display_deps() { pkg_install_display_deps; }
pkg_install_display_deps() {
    local deps=()

    case "${DISTRO_FAMILY:-}" in
        debian)
            deps=("xvfb" "x11vnc" "chromium")
            ;;
        fedora)
            deps=("xvfb" "x11vnc" "chromium")
            ;;
        arch)
            deps=("xvfb" "x11vnc" "chromium")
            ;;
        suse)
            deps=("xvfb" "x11vnc" "chromium")
            ;;
        alpine)
            deps=("xvfb" "chromium")
            ;;
        termux)
            deps=("chromium")
            ;;
        macos)
            # macOS doesn't need Xvfb
            deps=()
            ;;
        *)
            deps=("xvfb" "chromium")
            ;;
    esac

    echo "Installing display dependencies..."
    for dep in "${deps[@]}"; do
        pkg_install "$dep"
    done
}
