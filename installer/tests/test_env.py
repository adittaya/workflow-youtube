import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from installer.core.env import OSInfo, detect
from installer.platforms import detect_platform
from installer.core.executor import check_command, run_command


class TestEnvDetection(unittest.TestCase):
    def test_detect_returns_osinfo(self):
        info = detect()
        self.assertIsInstance(info, OSInfo)
        self.assertIn(info.system, ["Linux", "Darwin", "Windows", "Termux"])

    def test_detect_arch(self):
        info = detect()
        self.assertIn(info.arch, ["x86_64", "aarch64", "armv7l", "arm64", "AMD64", "i686", "armv6l"])

    def test_detect_has_shell(self):
        info = detect()
        self.assertIn(info.shell, ["bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh", "powershell", "cmd", "unknown"])

    def test_detect_has_package_manager(self):
        info = detect()
        self.assertIsInstance(info.package_manager, str)
        self.assertGreater(len(info.package_manager), 0)

    def test_detect_is_root(self):
        info = detect()
        self.assertIsInstance(info.is_root, bool)


class TestPlatformDetection(unittest.TestCase):
    def test_detect_platform(self):
        platform = detect_platform()
        self.assertIn(platform.name, ["linux", "macos", "windows", "termux"])
        self.assertIn(platform.arch, ["x86_64", "aarch64", "armv7l", "arm64", "AMD64", "i686", "armv6l"])

    def test_config_dirs_exist(self):
        platform = detect_platform()
        self.assertTrue(platform.config_dir.startswith("/") or ":" in platform.config_dir)
        self.assertTrue(platform.home.startswith("/") or ":" in platform.home)

    def test_platform_has_user(self):
        platform = detect_platform()
        self.assertIsInstance(platform.user, str)
        self.assertGreater(len(platform.user), 0)

    def test_platform_has_home(self):
        platform = detect_platform()
        self.assertIsInstance(platform.home, str)
        self.assertTrue(len(platform.home) > 0)


class TestExecutor(unittest.TestCase):
    def test_check_command_exists(self):
        self.assertTrue(check_command("python3") or check_command("python"))

    def test_check_command_missing(self):
        self.assertFalse(check_command("nonexistent_command_xyz123"))

    def test_run_command_success(self):
        result = run_command(["echo", "hello"], capture=True)
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello", result.stdout)

    def test_run_command_failure(self):
        result = run_command(["false"], capture=True)
        self.assertFalse(result.success)
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
