#!/usr/bin/env bash
set -euo pipefail

# ⚡ Installer — One-Line Full Environment Setup
# Usage: curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/installer/setup.sh | bash
# Or:    curl -fsSL ... | bash -s -- --packages git,nodejs,python3

INSTALLER_VERSION="1.0.0"
REPO="adittaya/workflow-vplink"
INSTALL_DIR="${HOME}/.local/bin"
CONFIG_DIR="${HOME}/.config/installer"
LOG_DIR="${HOME}/.local/share/installer/logs"
TEMP_DIR="/tmp/installer-setup"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

# Helpers
info()    { echo -e "${BLUE}ℹ${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗${NC} $*"; }
step()    { echo -e "${BLUE}⚡${NC} ${BOLD}$*${NC}"; }
dim()     { echo -e "${GRAY}$*${NC}"; }

# Parse args
PACKAGES=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --packages) PACKAGES="$2"; shift 2 ;;
    --upgrade) UPGRADE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) echo "Usage: $0 [--packages pkg1,pkg2] [--upgrade] [--dry-run]"; exit 0 ;;
    *) shift ;;
  esac
done

echo ""
echo -e "${BLUE}⚡${NC} ${BOLD}Installer v${INSTALLER_VERSION}${NC} — Production-Grade Cross-Platform Setup"
echo ""

# ── Step 1: Detect Environment ──
step "Detecting environment..."

detect_os() {
  case "$(uname -s)" in
    Linux*)   echo "linux" ;;
    Darwin*)  echo "macos" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *)        echo "unknown" ;;
  esac
}

detect_distro() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    echo "${ID:-unknown}"
  else
    echo "unknown"
  fi
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64)  echo "x64" ;;
    aarch64|arm64) echo "arm64" ;;
    armv7l|armhf)  echo "armv7" ;;
    *)             echo "unknown" ;;
  esac
}

detect_pkg_manager() {
  if command -v apt-get &>/dev/null; then echo "apt"
  elif command -v dnf &>/dev/null; then echo "dnf"
  elif command -v yum &>/dev/null; then echo "yum"
  elif command -v pacman &>/dev/null; then echo "pacman"
  elif command -v zypper &>/dev/null; then echo "zypper"
  elif command -v brew &>/dev/null; then echo "brew"
  elif command -v pkg &>/dev/null; then echo "pkg"
  else echo "none"; fi
}

detect_shell_profile() {
  case "$SHELL" in
    */zsh)  echo "${HOME}/.zshrc" ;;
    */bash)
      if [[ -f "${HOME}/.bash_profile" ]]; then echo "${HOME}/.bash_profile"
      else echo "${HOME}/.bashrc"; fi ;;
    */fish) echo "${HOME}/.config/fish/config.fish" ;;
    *)      echo "${HOME}/.profile" ;;
  esac
}

OS=$(detect_os)
DISTRO=$(detect_distro)
ARCH=$(detect_arch)
PKG_MGR=$(detect_pkg_manager)
SHELL_PROFILE=$(detect_shell_profile)
IS_ROOT=$([[ $EUID -eq 0 ]] && echo "yes" || echo "no")

dim "  OS:        ${OS}"
dim "  Distro:    ${DISTRO}"
dim "  Arch:      ${ARCH}"
dim "  Pkg mgr:   ${PKG_MGR}"
dim "  Shell:     ${SHELL_PROFILE}"
dim "  Root:      ${IS_ROOT}"
echo ""

# ── Step 2: Create Directories ──
step "Creating directories..."
mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}" "${LOG_DIR}" "${TEMP_DIR}"
success "Directories created"
echo ""

# ── Step 3: Update Package Index ──
step "Updating package index..."
case $PKG_MGR in
  apt)    sudo apt-get update -qq 2>/dev/null || true ;;
  dnf)    sudo dnf check-update -q 2>/dev/null || true ;;
  yum)    sudo yum check-update -q 2>/dev/null || true ;;
  pacman) sudo pacman -Sy --noconfirm 2>/dev/null || true ;;
  brew)   brew update 2>/dev/null || true ;;
  pkg)    pkg update -y 2>/dev/null || true ;;
esac
success "Package index updated"
echo ""

# ── Step 4: Install Packages ──
install_pkg() {
  local pkg="$1"
  local display="$2"

  # Check if already installed
  if command -v "$pkg" &>/dev/null || dpkg -l "$pkg" 2>/dev/null | grep -q "^ii" || rpm -q "$pkg" 2>/dev/null | grep -q "installed"; then
    dim "  — ${display} (already installed)"
    return 0
  fi

  info "Installing ${display}..."
  case $PKG_MGR in
    apt)    DEBIAN_FRONTEND=noninteractive sudo apt-get install -y -qq "$pkg" 2>/dev/null ;;
    dnf)    sudo dnf install -y -q "$pkg" 2>/dev/null ;;
    yum)    sudo yum install -y -q "$pkg" 2>/dev/null ;;
    pacman) sudo pacman -S --noconfirm "$pkg" 2>/dev/null ;;
    brew)   brew install "$pkg" 2>/dev/null ;;
    zypper) sudo zypper install -y -n "$pkg" 2>/dev/null ;;
    pkg)    pkg install -y "$pkg" 2>/dev/null ;;
    *)      warn "No package manager for ${display}"; return 1 ;;
  esac
  success "${display} installed"
}

step "Installing packages..."
echo ""

# Core packages
dim "  Core:"
install_pkg git Git
install_pkg curl cURL
install_pkg wget Wget
install_pkg unzip Unzip
echo ""

# Dev tools
dim "  Dev Tools:"
install_pkg build-essential "Build Essential" || {
  # Fallback for non-Debian
  case $PKG_MGR in
    dnf|yum) sudo dnf install -y gcc gcc-c++ make 2>/dev/null && success "Build tools installed" ;;
    pacman) sudo pacman -S --noconfirm base-devel 2>/dev/null && success "Build tools installed" ;;
  esac
}
echo ""

# Languages
dim "  Languages:"
install_pkg python3 Python3
install_pkg nodejs Node.js || {
  # Node.js may need special install
  if command -v node &>/dev/null; then
    dim "  — Node.js (already installed via other method)"
  else
    info "  Installing Node.js via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_lts.x 2>/dev/null | sudo -E bash - 2>/dev/null || true
    sudo apt-get install -y -qq nodejs 2>/dev/null || true
    command -v node &>/dev/null && success "Node.js installed" || warn "Node.js install failed"
  fi
}
echo ""

# CLI Tools
dim "  Tools:"
install_pkg htop htop
install_pkg tmux tmux
install_pkg jq jq
install_pkg tree Tree
echo ""

# ── Step 5: Install Bun (if not present) ──
if ! command -v bun &>/dev/null; then
  info "Installing Bun..."
  curl -fsSL https://bun.sh/install 2>/dev/null | bash 2>/dev/null || true
  export PATH="${HOME}/.bun/bin:$PATH"
  command -v bun &>/dev/null && success "Bun installed" || warn "Bun install failed"
else
  dim "  — Bun (already installed)"
fi
echo ""

# ── Step 6: Install GitHub CLI ──
if ! command -v gh &>/dev/null; then
  info "Installing GitHub CLI..."
  case $PKG_MGR in
    apt)
      curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg 2>/dev/null | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null || true
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null 2>&1
      sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y -qq gh 2>/dev/null || true
      ;;
    dnf|yum) sudo $PKG_MGR install -y 'dnf-command(config-manager)' 2>/dev/null && sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo 2>/dev/null && sudo $PKG_MGR install -y gh 2>/dev/null || true ;;
    brew) brew install gh 2>/dev/null ;;
    pacman) sudo pacman -S --noconfirm github-cli 2>/dev/null ;;
    *) warn "GitHub CLI not available via ${PKG_MGR}" ;;
  esac
  command -v gh &>/dev/null && success "GitHub CLI installed" || warn "GitHub CLI install failed"
else
  dim "  — GitHub CLI (already installed)"
fi
echo ""

# ── Step 7: Configure PATH ──
step "Configuring PATH..."
PROFILE_CONTENT=""
if [[ -f "$SHELL_PROFILE" ]]; then
  PROFILE_CONTENT=$(cat "$SHELL_PROFILE")
fi

if [[ "$SHELL_PROFILE" == *"fish"* ]]; then
  if ! echo "$PROFILE_CONTENT" | grep -q "fish_add_path.*\.local/bin"; then
    echo "fish_add_path -p ${HOME}/.local/bin" >> "$SHELL_PROFILE"
    success "PATH updated in ${SHELL_PROFILE}"
  else
    dim "  — PATH already configured"
  fi
else
  if ! echo "$PROFILE_CONTENT" | grep -q "\.local/bin"; then
    echo "" >> "$SHELL_PROFILE"
    echo "# Added by Installer v${INSTALLER_VERSION}" >> "$SHELL_PROFILE"
    echo "export PATH=\"${HOME}/.local/bin:\$PATH\"" >> "$SHELL_PROFILE"
    success "PATH updated in ${SHELL_PROFILE}"
  else
    dim "  — PATH already configured"
  fi
fi
echo ""

# ── Step 8: Write Config ──
step "Writing configuration..."
cat > "${CONFIG_DIR}/config.json" << EOF
{
  "version": "${INSTALLER_VERSION}",
  "installDir": "${INSTALL_DIR}",
  "configDir": "${CONFIG_DIR}",
  "logDir": "${LOG_DIR}",
  "packages": ["git", "curl", "wget", "unzip", "build-essential", "nodejs", "python3", "htop", "tmux", "jq", "tree", "bun", "gh"],
  "installedAt": "$(date -Iseconds)",
  "platform": {
    "os": "${OS}",
    "distro": "${DISTRO}",
    "arch": "${ARCH}",
    "pkgManager": "${PKG_MGR}"
  }
}
EOF
success "Config saved to ${CONFIG_DIR}/config.json"
echo ""

# ── Step 9: Verify ──
step "Verifying installation..."
echo ""

INSTALLED=0
MISSING=0

check_cmd() {
  local cmd="$1"
  local name="$2"
  if command -v "$cmd" &>/dev/null; then
    local ver=$($cmd --version 2>/dev/null | head -1 || echo "?")
    success "  ${name}: ${ver}"
    ((INSTALLED++))
  else
    error "  ${name}: NOT FOUND"
    ((MISSING++))
  fi
}

check_cmd git Git
check_cmd curl cURL
check_cmd wget Wget
check_cmd unzip Unzip
check_cmd python3 Python3
check_cmd node Node.js
check_cmd npm NPM
check_cmd bun Bun
check_cmd gh GitHub-CLI
check_cmd htop htop
check_cmd tmux tmux
check_cmd jq jq
check_cmd tree Tree
echo ""

# ── Summary ──
echo -e "──────────────────────────────────────────────────"
TOTAL=$((INSTALLED + MISSING))
if [[ $MISSING -eq 0 ]]; then
  success "${BOLD}Setup complete!${NC} ${INSTALLED}/${TOTAL} packages installed"
else
  warn "${BOLD}Setup complete with warnings${NC} ${INSTALLED}/${TOTAL} packages installed"
fi

echo ""
dim "Logs: ${LOG_DIR}"
dim "Config: ${CONFIG_DIR}/config.json"
echo ""
echo -e "  ${YELLOW}Restart your shell or run:${NC}"
echo -e "  ${YELLOW}source ${SHELL_PROFILE}${NC}"
echo ""
