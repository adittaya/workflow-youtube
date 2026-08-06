"""Interactive terminal UI: welcome screen, progress, menus, prompts.

All UI helpers degrade to non-interactive behaviour (sensible defaults, no
prompts, no spinners) when stdin is not a TTY or ``--non-interactive`` is set,
so the installer is safe to run from CI and one-liners.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from typing import Dict, Optional, Sequence, Tuple

from installer.core import utils

C = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "red": "\x1b[31m",
    "cyan": "\x1b[36m",
    "magenta": "\x1b[35m",
}


def _colors(enabled: bool) -> Dict[str, str]:
    if not enabled or os.environ.get("NO_COLOR"):
        return {k: "" for k in C}
    return C


def _unicode_safe() -> bool:
    """True if stdout can encode non-ASCII glyphs (not e.g. Windows cp1252)."""
    try:
        "✓✗⚠·╔═║╚╝⠋".encode(sys.stdout.encoding or "ascii", "strict")
        return True
    except (LookupError, UnicodeEncodeError):
        return False


SYM = (
    {"ok": "✓ ", "error": "✗ ", "warn": "⚠ ", "info": "· ",
     "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝", "h": "═", "v": "║",
     "frames": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"}
    if _unicode_safe()
    else {"ok": "+ ", "error": "! ", "warn": "! ", "info": "- ",
          "tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|",
          "frames": "|/-\\"}
)


class UI:
    def __init__(self, log=None, non_interactive: Optional[bool] = None,
                 color: Optional[bool] = None):
        self.log = log
        tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self.color = _colors(color if color is not None else tty)
        self.interactive = not (non_interactive if non_interactive is not None
                                else not tty)

    # -- output helpers ----------------------------------------------------
    def _paint(self, text: str, keys: Sequence[str]) -> str:
        for k in keys:
            text = f"{self.color.get(k, '')}{text}"
        return text + self.color.get("reset", "")

    def line(self, text: str = "") -> None:
        print(text, flush=True)

    def title(self, text: str) -> None:
        print(self._paint(text, ["bold"]), flush=True)

    def dim(self, text: str) -> None:
        print(self._paint(text, ["dim"]), flush=True)

    def ok(self, text: str) -> None:
        print(self._paint(SYM["ok"], ["green"]) + text, flush=True)

    def info(self, text: str) -> None:
        print(self._paint(SYM["info"], ["cyan"]) + text, flush=True)

    def warn(self, text: str) -> None:
        print(self._paint(SYM["warn"], ["yellow"]) + text, flush=True)

    def error(self, text: str) -> None:
        print(self._paint(SYM["error"], ["red"]) + text, flush=True)

    # -- screens -----------------------------------------------------------
    def welcome(self, app: str, version: str, tagline: str) -> None:
        width = 64
        print(self._paint(SYM["tl"] + SYM["h"] * width + SYM["tr"], ["cyan"]))
        for line in (f"{app.upper()} BOOTSTRAP INSTALLER", tagline, f"version {version}"):
            pad = max(0, width - len(line))
            print(self._paint(SYM["v"] + " ", ["cyan"]) + line + " " * pad + self._paint(" " + SYM["v"], ["cyan"]))
        print(self._paint(SYM["bl"] + SYM["h"] * width + SYM["br"], ["cyan"]))
        print()

    def success_summary(self, items: Sequence[Tuple[str, str]]) -> None:
        print()
        print(self._paint(SYM["ok"] + "INSTALLATION COMPLETE", ["green", "bold"]))
        for label, value in items:
            print(f"  {label:<28} {value}")

    # -- progress ----------------------------------------------------------
    def begin_step(self, text: str) -> None:
        print(self._paint("  " + text + " ...", ["dim"]), end="", flush=True)
        if self.log:
            self.log.step(text)

    def complete_step(self, text: str) -> None:
        print("\r" + self._paint(SYM["ok"], ["green"]) + text + " " * 8, flush=True)

    @contextlib.contextmanager
    def spinner(self, message: str = "Working", delay: float = 0.1):
        """Context manager showing an animated spinner while a block runs."""
        stop = threading.Event()

        def animate():
            frames = SYM["frames"]
            i = 0
            while not stop.is_set():
                frame = frames[i % len(frames)]
                print(f"\r{frame} {message} ...", end="", flush=True)
                i += 1
                stop.wait(delay)

        thread = threading.Thread(target=animate, daemon=True)
        if self.interactive:
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if self.interactive:
                thread.join(timeout=delay * 2)
                print("\r" + " " * 40 + "\r", end="", flush=True)

    # -- prompts -----------------------------------------------------------
    def confirm(self, prompt: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        return utils.confirm(prompt, default)

    def ask(self, prompt: str, default: str = "") -> str:
        if not self.interactive:
            return default
        return utils.ask(prompt, default)

    def menu(self, prompt: str, options: Sequence[Tuple[str, str, str]],
             default_key: Optional[str] = None) -> str:
        """Show a numbered menu, return the chosen key. ``q`` cancels.

        ``options`` is a list of (key, label, description).
        """
        if not self.interactive:
            return default_key or (options[0][0] if options else "")
        print()
        print(self._paint(prompt, ["bold"]))
        for idx, (key, label, desc) in enumerate(options, 1):
            marker = " >" if key == default_key else "  "
            print(f"{marker} {idx}. {label}")
            if desc:
                print(f"      {self._paint(desc, ['dim'])}")
        print(self._paint("  0. Cancel", ["dim"]))
        keys = [o[0] for o in options]
        while True:
            raw = input("  Choose [1-%d, 0=cancel]: " % len(options)).strip()
            if raw in ("0", "q", "cancel"):
                return ""
            if raw in keys:
                return raw
            try:
                num = int(raw)
                if 1 <= num <= len(options):
                    return keys[num - 1]
            except ValueError:
                pass
            print(self._paint("  Invalid choice.", ["red"]))
