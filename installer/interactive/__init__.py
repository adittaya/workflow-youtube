"""
Interactive CLI module.
Provides animated progress, prompts, menus, and colored terminal output.
"""
import sys
import time
import threading
from typing import Optional

from installer import logging as log


SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
PROGRESS_BAR_WIDTH = 40


class Spinner:
    """Animated spinner for long-running operations."""

    def __init__(self, message: str = ""):
        self.message = message
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        if not sys.stdout.isatty():
            print(f"  {self.message}...")
            return
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self):
        i = 0
        while self._running:
            chars = SPINNER_CHARS[i % len(SPINNER_CHARS)]
            sys.stdout.write(f"\r  \033[36m{chars}\033[0m {self.message}")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1
        sys.stdout.write(f"\r  \033[32m✓\033[0m {self.message}\n")
        sys.stdout.flush()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)


class ProgressBar:
    """Progress bar for downloads and multi-step operations."""

    def __init__(self, total: int = 100, prefix: str = ""):
        self.total = total
        self.prefix = prefix
        self.current = 0

    def update(self, value: float):
        self.current = int(value * self.total)
        self._draw()

    def _draw(self):
        if not sys.stdout.isatty():
            return
        pct = min(self.current / self.total, 1.0)
        filled = int(PROGRESS_BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (PROGRESS_BAR_WIDTH - filled)
        sys.stdout.write(
            f"\r  {self.prefix} [{bar}] {int(pct * 100)}%"
        )
        sys.stdout.flush()
        if pct >= 1.0:
            print()


def confirm(prompt: str, default: bool = True) -> bool:
    """Ask user for yes/no confirmation."""
    hint = "Y/n" if default else "y/N"
    response = input(f"  {prompt} [{hint}] ").strip().lower()
    if not response:
        return default
    return response[0] == "y"


def choose(label: str, options: list[str], default: int = 0) -> int:
    """Present a numbered menu and return the selected index."""
    print(f"\n  {label}:")
    for i, opt in enumerate(options, 1):
        marker = "→" if i - 1 == default else " "
        print(f"    {marker} {i}) {opt}")
    while True:
        try:
            choice = input(f"\n  {'Select':>10} [1-{len(options)}]: ").strip()
            if not choice:
                return default
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(options)}")


def multi_select(label: str, options: list[str]) -> list[int]:
    """Present a multi-select checklist."""
    selected = set()
    print(f"\n  {label} (space to toggle, enter when done):")
    for i, opt in enumerate(options):
        print(f"    [ ] {i+1}) {opt}")

    while True:
        choice = input(f"\n  {'Toggle':>10} [number]: ").strip()
        if not choice:
            break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                if idx in selected:
                    selected.remove(idx)
                else:
                    selected.add(idx)
                # Redraw
                print(f"\033[{len(options)+1}A")
                for i, opt in enumerate(options):
                    mark = "✓" if i in selected else " "
                    print(f"    [{mark}] {i+1}) {opt}")
        except ValueError:
            break
    return sorted(selected)


def input_text(prompt: str, default: str = "", secret: bool = False) -> str:
    """Get text input from user."""
    if secret:
        import getpass
        val = getpass.getpass(f"  {prompt}: ")
    else:
        val = input(f"  {prompt}: ").strip()
    if not val:
        return default
    return val


def wait_key():
    """Wait for a key press."""
    input(f"\n  {'Press Enter to continue...'}")



def header(text: str):
    """Display a formatted header."""
    width = min(len(text) + 8, 60)
    print()
    print(f"  \033[36m{'╔' + '═' * (width-2) + '╗'}\033[0m")
    print(f"  \033[36m║\033[0m   \033[1m{text}\033[0m{' ' * (width - len(text) - 7)} \033[36m║\033[0m")
    print(f"  \033[36m{'╚' + '═' * (width-2) + '╝'}\033[0m")
    print()


def welcome():
    """Display welcome screen."""
    header("VPLink 24/7 — Bootstrap Installer")
    print(f"  \033[2m{'Cross-platform environment bootstrapper'}\033[0m")
    print(f"  \033[2m{'Linux · macOS · Windows · Termux'}\033[0m")
    print()
