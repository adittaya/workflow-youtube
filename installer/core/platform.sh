#!/usr/bin/env bash
# ============================================================================
# platform.sh — OS/Distro/Arch/Environment Detection Module
# ============================================================================
# Detects: OS type, distribution, architecture, libc, package manager,
#          root status, Docker, WSL, CI, Termux, shell type, CPU, RAM,
#          and network connectivity.
#
# Exports globals: OS, DISTRO, DISTRO_FAMILY, ARCH, LIBC, PKG_MANAGER,
#   PKG_INSTALL, PKG_UPDATE, PKG_QUERY, SUDO, IS_ROOT, IS_DOCKER,
#   IS_WSL, IS_CI, IS_TERMUX, SHELL_TYPE, CPU_COUNT, RAM_MB
# ============================================================================

# Prevent double-sourcing
[[ -n "${_PLATFORM_LOADED:-}" ]] && return 0
_PLATFORM_LOADED=1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# has_cmd — check if a command exists on PATH
platform_has_cmd() { has_cmd "$@"; }
has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

platform_detect_os() { detect_os; }
detect_os() {
    local kernel
    kernel="$(uname -s 2>/dev/null || echo Unknown)"
    case "$kernel" in
        Linux*)     OS="linux" ;;
        Darwin*)    OS="macos" ;;
        CYGWIN*)    OS="windows" ;;
        MINGW*)     OS="windows" ;;
        MSYS*)      OS="windows" ;;
        *Haiku*)    OS="haiku" ;;
        *)          OS="unknown" ;;
    esac

    # Termux check (runs on Android/Linux but is distinct)
    IS_TERMUX=0
    if [[ -d "/data/data/com.termux/files/usr" ]] ||
       [[ -n "${TERMUX_VERSION:-}" ]] ||
       [[ "${PREFIX:-}" == *"com.termux"* ]]; then
        IS_TERMUX=1
        OS="termux"
    fi
    export OS IS_TERMUX
}

platform_detect_distro() { detect_distro; }
detect_distro() {
    DISTRO="unknown"
    DISTRO_FAMILY="unknown"

    # Termux is its own family
    if [[ "${IS_TERMUX:-0}" -eq 1 ]]; then
        DISTRO="termux"
        DISTRO_FAMILY="termux"
        # Still try to get the underlying Linux distro if possible
        if [[ -f /etc/os-release ]]; then
            DISTRO="$(. /etc/os-release && echo "${ID:-unknown}")"
        fi
        export DISTRO DISTRO_FAMILY
        return 0
    fi

    # macOS
    if [[ "${OS:-}" == "macos" ]]; then
        DISTRO="macos"
        DISTRO_FAMILY="macos"
        export DISTRO DISTRO_FAMILY
        return 0
    fi

    # Windows (MSYS/Cygwin) — detect the underlying distro if WSL
    if [[ "${OS:-}" == "windows" ]]; then
        DISTRO="windows"
        DISTRO_FAMILY="windows"
        # Check for WSL from inside MSYS
        if grep -qi microsoft /proc/version 2>/dev/null; then
            IS_WSL=1
        fi
        export DISTRO DISTRO_FAMILY
        return 0
    fi

    # Linux — read os-release
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        local id="${ID:-unknown}"
        local id_like="${ID_LIKE:-}"

        DISTRO="$id"

        case "$id" in
            ubuntu|debian|linuxmint|pop|elementary|zorin|kali|parrot|deepin|raspbian)
                DISTRO_FAMILY="debian" ;;
            fedora|rhel|centos|rocky|alma|ol|scientific|amzn|nobara)
                DISTRO_FAMILY="fedora" ;;
            arch|manjaro|endeavouros|garuda|arco)
                DISTRO_FAMILY="arch" ;;
            opensuse*|sles|suse)
                DISTRO_FAMILY="suse" ;;
            alpine|postmarketos)
                DISTRO_FAMILY="alpine" ;;
            void)
                DISTRO_FAMILY="void" ;;
            gentoo|funtoo)
                DISTRO_FAMILY="gentoo" ;;
            nixos)
                DISTRO_FAMILY="nixos" ;;
            *)
                # Fallback: check ID_LIKE
                if [[ -n "$id_like" ]]; then
                    case "$id_like" in
                        *debian*)   DISTRO_FAMILY="debian" ;;
                        *rhel*|*fedora*) DISTRO_FAMILY="fedora" ;;
                        *arch*)     DISTRO_FAMILY="arch" ;;
                        *suse*)     DISTRO_FAMILY="suse" ;;
                        *alpine*)   DISTRO_FAMILY="alpine" ;;
                    esac
                fi
                ;;
        esac
    else
        # Fallback detection without os-release
        if has_cmd apt; then
            DISTRO_FAMILY="debian"
            DISTRO="debian"
        elif has_cmd dnf || has_cmd yum; then
            DISTRO_FAMILY="fedora"
            DISTRO="fedora"
        elif has_cmd pacman; then
            DISTRO_FAMILY="arch"
            DISTRO="arch"
        elif has_cmd apk; then
            DISTRO_FAMILY="alpine"
            DISTRO="alpine"
        elif has_cmd zypper; then
            DISTRO_FAMILY="suse"
            DISTRO="suse"
        fi
    fi

    export DISTRO DISTRO_FAMILY
}

platform_detect_arch() { detect_arch; }
detect_arch() {
    local machine
    machine="$(uname -m 2>/dev/null || echo unknown)"
    case "$machine" in
        x86_64|amd64|AMD64)      ARCH="x86_64" ;;
        aarch64|arm64|ARM64)     ARCH="aarch64" ;;
        armv7l|armhf|armv7)      ARCH="armv7l" ;;
        armv6l)                   ARCH="armv6l" ;;
        i*86|i386|i486|i586|i686) ARCH="x86" ;;
        s390x)                    ARCH="s390x" ;;
        ppc64le)                  ARCH="ppc64le" ;;
        riscv64)                  ARCH="riscv64" ;;
        *)                        ARCH="$machine" ;;
    esac
    export ARCH
}

platform_detect_libc() { detect_libc; }
detect_libc() {
    LIBC="unknown"
    if has_cmd ldd; then
        local ldd_output
        ldd_output="$(ldd --version 2>&1 || true)"
        if echo "$ldd_output" | grep -qi "musl"; then
            LIBC="musl"
        else
            LIBC="glibc"
        fi
    elif [[ -f /lib/ld-musl-* ]] || [[ -f /lib/ld-musl*.so.1 ]]; then
        LIBC="musl"
    elif [[ -f /lib/x86_64-linux-gnu/libc.so.6 ]] || \
         [[ -f /lib/aarch64-linux-gnu/libc.so.6 ]] || \
         [[ -f /usr/lib/libc.so.6 ]] || \
         [[ -f /lib/libc.so.6 ]]; then
        LIBC="glibc"
    fi

    # Alpine always musl
    if [[ "${DISTRO_FAMILY:-}" == "alpine" ]]; then
        LIBC="musl"
    fi
    # Termux uses Bionic (Android libc)
    if [[ "${IS_TERMUX:-0}" -eq 1 ]]; then
        LIBC="bionic"
    fi

    export LIBC
}

platform_detect_pkg_manager() { detect_pkg_manager; }
detect_pkg_manager() {
    PKG_MANAGER="none"
    PKG_INSTALL=""
    PKG_UPDATE=""
    PKG_QUERY=""

    # Termux always uses pkg
    if [[ "${IS_TERMUX:-0}" -eq 1 ]]; then
        PKG_MANAGER="pkg"
        PKG_INSTALL="pkg install -y"
        PKG_UPDATE="pkg update -y"
        PKG_QUERY="pkg list-installed"
        export PKG_MANAGER PKG_INSTALL PKG_UPDATE PKG_QUERY
        return 0
    fi

    # macOS uses brew (or port/port)
    if [[ "${OS:-}" == "macos" ]]; then
        if has_cmd brew; then
            PKG_MANAGER="brew"
            PKG_INSTALL="brew install"
            PKG_UPDATE="brew update"
            PKG_QUERY="brew list --formula"
        fi
        export PKG_MANAGER PKG_INSTALL PKG_UPDATE PKG_QUERY
        return 0
    fi

    # Windows MSYS — use pacman (MSYS2) or winget
    if [[ "${OS:-}" == "windows" ]]; then
        if has_cmd pacman; then
            PKG_MANAGER="pacman-msys"
            PKG_INSTALL="pacman -S --noconfirm"
            PKG_UPDATE="pacman -Sy"
            PKG_QUERY="pacman -Qi"
        elif has_cmd winget; then
            PKG_MANAGER="winget"
            PKG_INSTALL="winget install --accept-package-agreements --accept-source-agreements"
            PKG_UPDATE="winget source update"
            PKG_QUERY="winget list"
        elif has_cmd choco; then
            PKG_MANAGER="choco"
            PKG_INSTALL="choco install -y"
            PKG_UPDATE="choco upgrade all -y"
            PKG_QUERY="choco list --local-only"
        fi
        export PKG_MANAGER PKG_INSTALL PKG_UPDATE PKG_QUERY
        return 0
    fi

    # Linux
    case "${DISTRO_FAMILY:-}" in
        debian)
            PKG_MANAGER="apt"
            PKG_INSTALL="apt-get install -y"
            PKG_UPDATE="apt-get update -qq"
            PKG_QUERY="dpkg -s"
            ;;
        fedora)
            if has_cmd dnf; then
                PKG_MANAGER="dnf"
                PKG_INSTALL="dnf install -y"
                PKG_UPDATE="dnf check-update || true"
                PKG_QUERY="rpm -q"
            else
                PKG_MANAGER="yum"
                PKG_INSTALL="yum install -y"
                PKG_UPDATE="yum check-update || true"
                PKG_QUERY="rpm -q"
            fi
            ;;
        arch)
            PKG_MANAGER="pacman"
            PKG_INSTALL="pacman -S --noconfirm --needed"
            PKG_UPDATE="pacman -Sy"
            PKG_QUERY="pacman -Qi"
            ;;
        suse)
            PKG_MANAGER="zypper"
            PKG_INSTALL="zypper install -y --no-confirm"
            PKG_UPDATE="zypper refresh"
            PKG_QUERY="rpm -q"
            ;;
        alpine)
            PKG_MANAGER="apk"
            PKG_INSTALL="apk add --no-cache"
            PKG_UPDATE="apk update"
            PKG_QUERY="apk info -e"
            ;;
        *)
            # Fallback: probe for known managers
            if has_cmd apt-get; then
                PKG_MANAGER="apt"
                PKG_INSTALL="apt-get install -y"
                PKG_UPDATE="apt-get update -qq"
                PKG_QUERY="dpkg -s"
            elif has_cmd dnf; then
                PKG_MANAGER="dnf"
                PKG_INSTALL="dnf install -y"
                PKG_UPDATE="dnf check-update || true"
                PKG_QUERY="rpm -q"
            elif has_cmd yum; then
                PKG_MANAGER="yum"
                PKG_INSTALL="yum install -y"
                PKG_UPDATE="yum check-update || true"
                PKG_QUERY="rpm -q"
            elif has_cmd pacman; then
                PKG_MANAGER="pacman"
                PKG_INSTALL="pacman -S --noconfirm --needed"
                PKG_UPDATE="pacman -Sy"
                PKG_QUERY="pacman -Qi"
            elif has_cmd zypper; then
                PKG_MANAGER="zypper"
                PKG_INSTALL="zypper install -y --no-confirm"
                PKG_UPDATE="zypper refresh"
                PKG_QUERY="rpm -q"
            elif has_cmd apk; then
                PKG_MANAGER="apk"
                PKG_INSTALL="apk add --no-cache"
                PKG_UPDATE="apk update"
                PKG_QUERY="apk info -e"
            fi
            ;;
    esac

    export PKG_MANAGER PKG_INSTALL PKG_UPDATE PKG_QUERY
}

# ---------------------------------------------------------------------------
# Boolean detection functions
# ---------------------------------------------------------------------------

platform_is_root() { is_root; }
is_root() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        IS_ROOT=1
    else
        IS_ROOT=0
    fi
    export IS_ROOT
}

platform_is_docker() { is_docker; }
is_docker() {
    IS_DOCKER=0
    # /.dockerenv is the canonical indicator
    if [[ -f /.dockerenv ]]; then
        IS_DOCKER=1
    fi
    # cgroup check (Docker puts container ID in cgroup)
    if [[ -f /proc/1/cgroup ]]; then
        if grep -qE '(/docker/|/lxc/|/kubepods/)' /proc/1/cgroup 2>/dev/null; then
            IS_DOCKER=1
        fi
    fi
    # containerenv for podman
    if [[ -f /run/.containerenv ]]; then
        IS_DOCKER=1
    fi
    # OCI container spec
    if [[ -f /.flatpak-info ]] || [[ -f /run/.ostree-booted ]]; then
        IS_DOCKER=1
    fi
    export IS_DOCKER
}

platform_is_wsl() { is_wsl; }
is_wsl() {
    IS_WSL=0
    # Check proc version
    if [[ -f /proc/version ]]; then
        if grep -qi microsoft /proc/version 2>/dev/null; then
            IS_WSL=1
        fi
    fi
    # Check WSL env var (set by WSL itself)
    if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
        IS_WSL=1
    fi
    # Check for WSL interop
    if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
        IS_WSL=1
    fi
    # Check for Windows executables accessible
    if [[ -d "/mnt/c/Windows/System32" ]]; then
        IS_WSL=1
    fi
    export IS_WSL
}

platform_is_ci() { is_ci; }
is_ci() {
    IS_CI=0
    # Check common CI environment variables
    if [[ -n "${CI:-}" ]] || [[ -n "${GITHUB_ACTIONS:-}" ]] ||
       [[ -n "${GITLAB_CI:-}" ]] || [[ -n "${TRAVIS:-}" ]] ||
       [[ -n "${CIRCLECI:-}" ]] || [[ -n "${JENKINS_URL:-}" ]] ||
       [[ -n "${BUILDKITE:-}" ]] || [[ -n "${TF_BUILD:-}" ]] ||
       [[ -n "${BITBUCKET_BUILD_NUMBER:-}" ]] || [[ -n "${CODEBUILD_BUILD_ID:-}" ]] ||
       [[ -n "${HEROKU_TEST_RUN_ID:-}" ]] || [[ -n "${RENDER:-}" ]] ||
       [[ -n "${VERCEL:-}" ]] || [[ -n "${NETLIFY:-}" ]] ||
        [[ -n "${BUILD_ID:-}" ]]; then
        IS_CI=1
    fi
    export IS_CI
}

platform_is_termux() { is_termux; }
is_termux() {
    # Re-run detection if not set
    if [[ -z "${IS_TERMUX:-}" ]]; then
        detect_os
    fi
    # Return was set by detect_os
}

# ---------------------------------------------------------------------------
# Network check
# ---------------------------------------------------------------------------

platform_has_network() { has_network; }
has_network() {
    # Try multiple methods
    local result=1

    # Method 1: ping
    if has_cmd ping; then
        if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1 || \
           ping -c 1 -W 3 1.1.1.1 >/dev/null 2>&1; then
            result=0
        fi
    fi

    # Method 2: curl
    if [[ $result -ne 0 ]] && has_cmd curl; then
        if curl -sf --max-time 5 https://1.1.1.1 >/dev/null 2>&1 || \
           curl -sf --max-time 5 https://httpbin.org/get >/dev/null 2>&1; then
            result=0
        fi
    fi

    # Method 3: wget
    if [[ $result -ne 0 ]] && has_cmd wget; then
        if wget -q --spider --timeout=5 https://1.1.1.1 2>/dev/null; then
            result=0
        fi
    fi

    return $result
}

# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

platform_cpu_count() {
    CPU_COUNT=1
    if has_cmd nproc; then
        CPU_COUNT="$(nproc 2>/dev/null || echo 1)"
    elif has_cmd sysctl; then
        CPU_COUNT="$(sysctl -n hw.ncpu 2>/dev/null || echo 1)"
    elif [[ -f /proc/cpuinfo ]]; then
        CPU_COUNT="$(grep -c ^processor /proc/cpuinfo 2>/dev/null || echo 1)"
    fi
    export CPU_COUNT
}

platform_ram_mb() {
    RAM_MB=0
    if has_cmd free; then
        RAM_MB="$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo 0)"
    elif has_cmd sysctl; then
        local ram_bytes
        ram_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
        if [[ "$ram_bytes" -gt 0 ]]; then
            RAM_MB=$(( ram_bytes / 1024 / 1024 ))
        fi
    elif [[ -f /proc/meminfo ]]; then
        RAM_MB="$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
    fi
    export RAM_MB
}

# ---------------------------------------------------------------------------
# Shell detection
# ---------------------------------------------------------------------------

platform_detect_shell() {
    detect_shell
}

detect_shell() {
    SHELL_TYPE="unknown"
    local shell_name
    shell_name="$(basename "${SHELL:-/bin/sh}" 2>/dev/null || echo sh)"

    case "$shell_name" in
        bash)          SHELL_TYPE="bash" ;;
        zsh)           SHELL_TYPE="zsh" ;;
        fish)          SHELL_TYPE="fish" ;;
        powershell)    SHELL_TYPE="powershell" ;;
        pwsh)          SHELL_TYPE="powershell" ;;
        sh)            SHELL_TYPE="sh" ;;
        dash)          SHELL_TYPE="sh" ;;
        *)             SHELL_TYPE="$shell_name" ;;
    esac

    # Override for MSYS/Cygwin PowerShell
    if [[ "${OS:-}" == "windows" ]] && has_cmd pwsh; then
        SHELL_TYPE="powershell"
    fi

    export SHELL_TYPE
}

# ---------------------------------------------------------------------------
# Sudo detection
# ---------------------------------------------------------------------------

platform_detect_sudo() {
    SUDO=""
    if [[ "${IS_ROOT:-0}" -eq 0 ]]; then
        if has_cmd sudo; then
            SUDO="sudo"
        elif has_cmd doas; then
            SUDO="doas"
        fi
    fi
    export SUDO
}

# ---------------------------------------------------------------------------
# Master detection function
# ---------------------------------------------------------------------------

platform_detect_all() { detect_all; }
detect_all() {
    detect_os
    detect_distro
    detect_arch
    detect_libc
    is_root
    is_docker
    is_wsl
    is_ci
    detect_pkg_manager
    detect_shell
    platform_detect_sudo
    platform_cpu_count
    platform_ram_mb
}

# ---------------------------------------------------------------------------
# Pretty-print environment summary
# ---------------------------------------------------------------------------

platform_print_env_summary() { print_env_summary; }
print_env_summary() {
    echo ""
    echo "=========================================="
    echo "  Environment Summary"
    echo "=========================================="
    printf "  OS:             %s\n" "${OS:-?}"
    printf "  Distro:         %s\n" "${DISTRO:-?}"
    printf "  Distro Family:  %s\n" "${DISTRO_FAMILY:-?}"
    printf "  Architecture:   %s\n" "${ARCH:-?}"
    printf "  Libc:           %s\n" "${LIBC:-?}"
    printf "  Package Mgr:    %s\n" "${PKG_MANAGER:-none}"
    printf "  Shell:          %s\n" "${SHELL_TYPE:-?}"
    printf "  CPU Cores:      %s\n" "${CPU_COUNT:-?}"
    printf "  RAM:            %s MB\n" "${RAM_MB:-?}"
    printf "  Root:           %s\n" "${IS_ROOT:-0}"
    printf "  Docker:         %s\n" "${IS_DOCKER:-0}"
    printf "  WSL:            %s\n" "${IS_WSL:-0}"
    printf "  CI:             %s\n" "${IS_CI:-0}"
    printf "  Termux:         %s\n" "${IS_TERMUX:-0}"
    echo "=========================================="
    echo ""
}

# ---------------------------------------------------------------------------
# Auto-detect when sourced (optional — only if PLATFORM_AUTO_DETECT=1)
# ---------------------------------------------------------------------------
if [[ "${PLATFORM_AUTO_DETECT:-0}" -eq 1 ]]; then
    detect_all
fi
