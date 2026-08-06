#!/usr/bin/env bash
# One-line bootstrap for yt-auto:
#   bash <(curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-youtube/main/bootstrap.sh)
#
# Downloads the latest source tarball from GitHub and runs the production
# installer on it. Arguments are passed through to the installer, so
# bootstrap.sh [--dry-run|install|doctor --fix|verify|...] all work.
set -e

REPO="adittaya/workflow-youtube"
BRANCH="main"

if [ ! -x /usr/bin/curl ] && [ ! -x /bin/curl ] && ! command -v curl &>/dev/null; then
    echo "ERROR: curl is required for the one-line bootstrap." >&2
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required (the installer itself runs on Python)." >&2
    echo "  Ubuntu/Debian: sudo apt-get install -y python3 python3-pip" >&2
    echo "  Fedora:        sudo dnf install -y python3 python3-pip" >&2
    echo "  Arch:          sudo pacman -S --noconfirm python python-pip" >&2
    echo "  macOS:         install Xcode CLT or Homebrew python" >&2
    exit 1
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "yt-auto bootstrap: fetching $REPO@$BRANCH ..."
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" -o "$TMP/repo.tgz"
tar -xzf "$TMP/repo.tgz" -C "$TMP"

SRC="$(find "$TMP" -maxdepth 1 -type d -name "workflow-youtube-*" | head -1)"
if [ -z "$SRC" ]; then
    echo "ERROR: could not extract the source tarball." >&2
    exit 1
fi

cd "$SRC"
python3 -m installer "$@"
