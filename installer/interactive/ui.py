import os
import sys
import time
import threading
from enum import Enum
from typing import Optional, Callable, Any

class Color(Enum):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"

    def __str__(self):
        return self.value if sys.stdout.isatty() else ""

def colored(text: str, *colors: Color) -> str:
    if not sys.stdout.isatty():
        return text
    prefix = "".join(str(c) for c in colors)
    return f"{prefix}{text}{Color.RESET}"

def heading(text: str):
    """Print a section heading."""
    try:
        width = min(60, os.get_terminal_size().columns) if hasattr(os, 'get_terminal_size') else 60
    except OSError:
        width = 60
    print()
    print(colored("╔" + "═" * (width - 2) + "╗", Color.BOLD, Color.CYAN))
    # Center text
    padding = (width - 2 - len(text)) // 2
    line = "║" + " " * padding + text + " " * (width - 2 - len(text) - padding) + "║"
    print(colored(line, Color.BOLD, Color.CYAN))
    print(colored("╚" + "═" * (width - 2) + "╝", Color.BOLD, Color.CYAN))
    print()

def status(message: str, kind: str = "info"):
    """Print a status line with colored prefix."""
    icons = {
        "info": colored("  •", Color.BLUE),
        "ok": colored("  ✓", Color.GREEN),
        "done": colored("  ✓", Color.GREEN),
        "error": colored("  ✗", Color.RED),
        "warn": colored("  ⚠", Color.YELLOW),
        "wait": colored("  ◷", Color.CYAN),
    }
    icon = icons.get(kind, icons["info"])
    print(f"{icon} {message}")
    sys.stdout.flush()

def success(message: str):
    """Print a success message."""
    print(colored(f"\n  ✓ {message}", Color.BOLD, Color.GREEN))

def error(message: str):
    """Print an error message."""
    print(colored(f"\n  ✗ {message}", Color.BOLD, Color.RED), file=sys.stderr)

def warn(message: str):
    """Print a warning message."""
    print(colored(f"\n  ⚠ {message}", Color.YELLOW))

def prompt(message: str, default: Optional[str] = None) -> str:
    """Prompt user for input with optional default."""
    if default:
        prompt_str = f"{colored('?', Color.CYAN)} {message} [{default}]: "
    else:
        prompt_str = f"{colored('?', Color.CYAN)} {message}: "
    try:
        value = input(prompt_str).strip()
        return value if value else (default or "")
    except (EOFError, KeyboardInterrupt):
        print()
        return default or ""

def confirm(message: str, default: bool = True) -> bool:
    """Ask for yes/no confirmation."""
    default_str = "Y/n" if default else "y/N"
    prompt_str = f"{colored('?', Color.CYAN)} {message} [{default_str}]: "
    try:
        value = input(prompt_str).strip().lower()
        if not value:
            return default
        return value.startswith("y")
    except (EOFError, KeyboardInterrupt):
        print()
        return False

def choose(message: str, options: list[str], default: Optional[int] = None) -> int:
    """Let user choose from a list. Returns index."""
    print(f"\n{colored('?', Color.CYAN)} {message}")
    for i, opt in enumerate(options, 1):
        default_mark = colored(" (default)", Color.DIM) if default == i else ""
        print(f"  {colored(str(i) + '.', Color.BOLD)} {opt}{default_mark}")

    default_val = str(default) if default else ""
    prompt_str = f"  Enter number [{default_val}]: "
    while True:
        try:
            value = input(prompt_str).strip()
            if not value and default:
                return default - 1
            idx = int(value) - 1
            if 0 <= idx < len(options):
                return idx
            print(colored(f"  Enter a number between 1 and {len(options)}", Color.RED))
        except (ValueError, EOFError, KeyboardInterrupt):
            if default:
                return default - 1
            print()

class Spinner:
    """A simple spinner for indefinite waits."""

    def __init__(self, message: str = ""):
        self.message = message
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        if not sys.stdout.isatty():
            print(f"  {self.message}...")
            sys.stdout.flush()
            return
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self):
        i = 0
        while self._running:
            char = self._chars[i % len(self._chars)]
            print(f"\r  {colored(char, Color.CYAN)} {self.message}...", end="", flush=True)
            time.sleep(0.1)
            i += 1

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        if sys.stdout.isatty():
            print(f"\r  {colored('✓', Color.GREEN)} {self.message}   ")
        else:
            print(f"  {self.message}... {colored('done', Color.GREEN)}")
        sys.stdout.flush()

class ProgressBar:
    """A simple progress bar."""

    def __init__(self, total: int, prefix: str = ""):
        self.total = total
        self.prefix = prefix
        self.current = 0
        self._width = 30

    def update(self, amount: int = 1):
        self.current += amount
        self._draw()

    def set(self, value: int):
        self.current = value
        self._draw()

    def _draw(self):
        if not sys.stdout.isatty() or self.total == 0:
            return
        pct = self.current / self.total
        filled = int(self._width * pct)
        bar = "█" * filled + "░" * (self._width - filled)
        pct_str = f"{pct * 100:.0f}%"
        print(f"\r  {self.prefix} [{bar}] {pct_str}", end="", flush=True)
        if self.current >= self.total:
            print()

    def __enter__(self):
        self._draw()
        return self

    def __exit__(self, *args):
        self.set(self.total)

def summary_box(title: str, items: list[tuple[str, str, str]]):
    """
    Print a summary box with items.
    items: list of (label, value, color_key) where color_key is 'ok', 'error', 'warn', 'info'
    """
    colors = {"ok": Color.GREEN, "error": Color.RED, "warn": Color.YELLOW, "info": Color.CYAN}
    width = min(60, max(len(title) + 4, 40))
    print()
    print(colored("╔" + "═" * (width - 2) + "╗", Color.BOLD))
    # Title line
    padding = (width - 2 - len(title)) // 2
    print(colored("║" + " " * padding + title + " " * (width - 2 - len(title) - padding) + "║", Color.BOLD))
    print(colored("╠" + "═" * (width - 2) + "╣", Color.BOLD))

    for label, value, color_key in items:
        color = colors.get(color_key, Color.WHITE)
        line = f"  {label}: {value}"
        print(colored(line, color))

    print(colored("╚" + "═" * (width - 2) + "╝", Color.BOLD))
    print()
