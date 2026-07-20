from installer.platforms.base import PlatformInfo, BasePlatform
from installer.platforms.linux import LinuxPlatform
from installer.platforms.macos import MacOSPlatform
from installer.platforms.windows import WindowsPlatform
from installer.platforms.termux import TermuxPlatform


def detect_platform() -> PlatformInfo:
    """Auto-detect current platform and return PlatformInfo."""
    import os
    import platform

    if os.environ.get("TERMUX_VERSION") or os.environ.get("PREFIX", "").startswith(
        "/data/data/com.termux"
    ):
        return TermuxPlatform.detect()

    system = platform.system()
    if system == "Linux":
        return LinuxPlatform.detect()
    elif system == "Darwin":
        return MacOSPlatform.detect()
    elif system == "Windows":
        return WindowsPlatform.detect()
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def get_platform() -> BasePlatform:
    """Get the platform handler for the current OS."""
    info = detect_platform()
    cls = {
        "linux": LinuxPlatform,
        "macos": MacOSPlatform,
        "windows": WindowsPlatform,
        "termux": TermuxPlatform,
    }[info.name]
    return cls
