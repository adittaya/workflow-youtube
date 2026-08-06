"""Tests for shell profile editing (idempotent, reversible)."""

import tempfile
import unittest
from pathlib import Path

from installer.core import shellprofile


class ShellProfileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.prof = shellprofile.ShellProfile(shell="bash", home=self.home)
        self.rc = self.home / ".bashrc"

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_path_creates_file_and_is_idempotent(self):
        binpath = self.home / ".local" / "bin"
        first = self.prof.add_path(binpath)
        second = self.prof.add_path(binpath)
        self.assertGreaterEqual(len(first), 1, "path should be added to at least one profile")
        self.assertEqual(second, [], "second add must be a no-op")
        text = self.rc.read_text()
        self.assertEqual(text.count(str(binpath)), 1)
        self.assertIn('export PATH="', text)

    def test_add_export_no_duplicate(self):
        self.prof.add_export("YT_MIRROR_HOME", "/tmp/x")
        self.prof.add_export("YT_MIRROR_HOME", "/tmp/x")
        lines = [l for l in self.rc.read_text().splitlines() if "YT_MIRROR_HOME" in l]
        self.assertEqual(len(lines), 1)

    def test_remove_path_cleans_up(self):
        binpath = self.home / ".local" / "bin"
        self.prof.add_path(binpath)
        changed = self.prof.remove_path(binpath)
        self.assertTrue(changed)
        self.assertEqual(self.rc.read_text().count(str(binpath)), 0)

    def test_remove_export_cleans_up(self):
        self.prof.add_export("FOO", "bar")
        self.prof.remove_export("FOO")
        self.assertNotIn("FOO", self.rc.read_text())

    def test_zsh_profile_location(self):
        p = shellprofile.ShellProfile(shell="zsh", home=self.home)
        self.assertEqual(p.files(), [self.home / ".zshrc"])

    def test_fish_syntax(self):
        p = shellprofile.ShellProfile(shell="fish", home=self.home)
        p.add_path(self.home / "bin")
        text = (self.home / ".config" / "fish" / "config.fish").read_text()
        self.assertIn("fish_add_path", text)

    def test_pwsh_syntax(self):
        p = shellprofile.ShellProfile(shell="pwsh", home=self.home)
        p.add_export("FOO", "bar")
        files = p.files()
        self.assertTrue(files)
        self.assertIn("$env:FOO", files[0].read_text())


if __name__ == "__main__":
    unittest.main()
