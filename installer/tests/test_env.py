"""Tests for environment detection and package helpers."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installer.core import env, packages as pkgmod
from installer.core.config import _load_yaml
from installer.core.packages import PackageRegistry, parse_version, version_meets


class EnvDetectionTests(unittest.TestCase):
    def test_system_is_linux_on_posix(self):
        if __import__("sys").platform.startswith("linux"):
            self.assertTrue(env.is_linux())

    def test_architecture_normalised(self):
        self.assertIn(env.architecture(), ("x86_64", "aarch64", "i386"))

    def test_display_environment_has_required_keys(self):
        for key in ("system", "architecture", "shell", "package_manager",
                    "python", "root", "admin"):
            self.assertIn(key, env.display_environment())

    def test_home_dir_resolved(self):
        self.assertTrue(str(env.home_dir()))


class CloudShellDetectionTests(unittest.TestCase):
    def test_env_var_detects(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CLOUD_SHELL": "true"}):
            self.assertTrue(env.is_cloud_shell())

    def test_marker_dir_detects(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".cloudshell").mkdir()
            with mock.patch.dict(os.environ, {"HOME": td, "GOOGLE_CLOUD_SHELL": ""}):
                self.assertTrue(env.is_cloud_shell())

    def test_absent_not_detected(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"HOME": td, "GOOGLE_CLOUD_SHELL": ""}):
                self.assertFalse(env.is_cloud_shell())


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("git version 2.43.0"), (2, 43, 0))
        self.assertEqual(parse_version("v26.5.1"), (26, 5, 1))
        self.assertEqual(parse_version("3.12.3"), (3, 12, 3))
        self.assertEqual(parse_version("no digits"), ())

    def test_version_meets(self):
        self.assertTrue(version_meets("2.43.0", "2.30"))
        self.assertFalse(version_meets("2.1.0", "2.30"))
        self.assertTrue(version_meets("1.0", ""))

    def test_registry_from_yaml(self):
        pkg_yaml = _load_yaml(
            "packages:\n"
            "  git:\n"
            "    verify: git\n"
            "    systems:\n"
            "      apt: [git]\n"
            "      brew: [git]\n"
        )
        reg = PackageRegistry.from_dict(pkg_yaml)
        self.assertIn("git", reg.names())
        self.assertEqual(reg.get("git").system_package_names("apt"), ["git"])
        self.assertEqual(reg.get("git").system_package_names("pacman"), [])

    def test_system_install_names(self):
        reg = PackageRegistry.from_yaml(Path(__file__).resolve().parents[1] / "packages.yaml")
        concrete, missing = reg.system_install_names("apt", ["git", "doesnotexist"])
        self.assertIn("git", concrete)
        self.assertEqual(missing, ["doesnotexist"])

    def test_check_package_returns_shape(self):
        reg = PackageRegistry.from_yaml(Path(__file__).resolve().parents[1] / "packages.yaml")
        info = pkgmod.check_package(reg, "git")
        for key in ("name", "verify", "installed", "version", "min_version", "min_ok", "optional"):
            self.assertIn(key, info)

    def test_python_check_requires_pip(self):
        # Fresh images ship python3 without pip; the python stage must then be
        # considered missing so python3-pip gets installed.
        reg = PackageRegistry.from_yaml(Path(__file__).resolve().parents[1] / "packages.yaml")
        base = {
            "python_version": "3.12.3",
            "python_meets_minimum": True,
        }
        with mock.patch.object(env, "python_version", return_value=base["python_version"]), \
             mock.patch.object(env, "python_meets_minimum", return_value=base["python_meets_minimum"]), \
             mock.patch.object(env, "pip_version", return_value="pip 24.0"):
            self.assertTrue(pkgmod.check_package(reg, "python")["installed"])
        with mock.patch.object(env, "python_version", return_value=base["python_version"]), \
             mock.patch.object(env, "python_meets_minimum", return_value=base["python_meets_minimum"]), \
             mock.patch.object(env, "pip_version", return_value=None):
            self.assertFalse(pkgmod.check_package(reg, "python")["installed"])

    def test_version_of_falls_back_to_single_dash(self):
        # ffmpeg only accepts '-version'; '--version' is an unknown option
        # (exit 8, stderr). version_of must fall back and still detect it.
        if env.version_of("ffmpeg") is None:
            self.skipTest("ffmpeg not installed on this machine")
        self.assertIsNotNone(env.version_of("ffmpeg"))
        self.assertIsNotNone(env.version_of("ffmpeg", "-version"))

    def test_probe_version_reads_stderr_on_zero_exit(self):
        from installer.core import utils

        script = "import sys; sys.stderr.write('probe 1.2.3\\n')"
        line = utils.probe_version([sys.executable, "-c", script])
        self.assertEqual(line, "probe 1.2.3")

    def test_probe_version_empty_on_missing_program(self):
        from installer.core import utils

        self.assertEqual(utils.probe_version(["definitely-not-a-real-binary-xyz"]), "")


if __name__ == "__main__":
    unittest.main()
