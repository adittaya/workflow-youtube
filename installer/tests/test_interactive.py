"""Tests for the interactive UI and update version logic."""

import io
import unittest
from contextlib import redirect_stdout

from installer.interactive import UI
from installer.update import Release, is_newer, _version_key


class UINonInteractiveTests(unittest.TestCase):
    def setUp(self):
        self.ui = UI(non_interactive=True, color=False)

    def test_confirm_uses_default(self):
        self.assertTrue(self.ui.confirm("?", default=True))
        self.assertFalse(self.ui.confirm("?", default=False))

    def test_ask_uses_default(self):
        self.assertEqual(self.ui.ask("?", default="d"), "d")

    def test_menu_uses_default_key(self):
        options = [("a", "A", ""), ("b", "B", "")]
        self.assertEqual(self.ui.menu("pick", options, default_key="b"), "b")

    def test_renders_without_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.ui.welcome("test", "1.0", "tagline")
            self.ui.ok("fine")
            self.ui.error("bad")
            self.ui.success_summary([("a", "b")])
        self.assertIn("BOOTSTRAP INSTALLER", buf.getvalue())

    def test_spinner_noop_non_interactive(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.ui.spinner("working"):
                pass


class UpdateVersionTests(unittest.TestCase):
    def test_version_key(self):
        self.assertEqual(_version_key("v1.2.3"), (1, 2, 3))
        self.assertEqual(_version_key("1.10"), (1, 10))

    def test_is_newer(self):
        old = Release("v1.0.0", "", "", "", "")
        new = Release("v1.1.0", "", "", "", "")
        self.assertTrue(is_newer(new, "1.0.0"))
        self.assertFalse(is_newer(old, "1.0.0"))
        self.assertFalse(is_newer(new, "1.2.0"))

    def test_changelog_limits_lines(self):
        rel = Release("v1.0.0", "", "\n".join(f"line{i}" for i in range(50)), "", "")
        self.assertEqual(len(update_changelog(rel).splitlines()), 20)


def update_changelog(rel, limit=20):
    lines = [l for l in rel.body.splitlines() if l.strip()]
    return "\n".join(lines[:limit])


if __name__ == "__main__":
    unittest.main()
