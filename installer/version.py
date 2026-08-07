"""Version and application identity for the installer."""

__version__ = "1.1.0"

#: The tool this installer bootstraps.
APP_NAME = "yt-auto"

#: The global command this installer installs for itself.
INSTALLER_NAME = "installer"

#: The global command that launches the interactive management TUI.
TUI_NAME = "YOUTUBE"

#: Upstream source this installer self-updates from (GitHub Releases).
REPO = "adittaya/workflow-youtube"

#: Minimum supported Python for the installed tooling.
MIN_PYTHON = (3, 10)
