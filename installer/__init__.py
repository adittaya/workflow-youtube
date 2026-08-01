"""yt-auto bootstrap installer.

A production-grade, cross-platform installer that bootstraps the yt-auto
environment (system packages, Python tooling, configuration, and the global
``installer`` / ``yt-auto`` commands) on Linux, macOS, Windows and Termux.
"""

from installer.version import __version__

__all__ = ["__version__"]
