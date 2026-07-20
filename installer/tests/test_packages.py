import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from installer.packages.definitions import PackageDef, PACKAGES, get_package, get_packages_by_category
from installer.packages.manager import PackageManager
from installer.verification.checker import Verifier, CheckResult


class TestPackageDefinitions(unittest.TestCase):
    def test_all_packages_have_name(self):
        for pkg in PACKAGES:
            self.assertTrue(pkg.name, f"Package missing name: {pkg}")

    def test_all_packages_have_display_name(self):
        for pkg in PACKAGES:
            self.assertTrue(pkg.display_name, f"Package {pkg.name} missing display_name")

    def test_all_packages_have_binary_check(self):
        for pkg in PACKAGES:
            self.assertTrue(pkg.binary_check, f"Package {pkg.name} missing binary_check")

    def test_git_package_has_apt_name(self):
        git = get_package("git")
        self.assertIsNotNone(git)
        self.assertEqual(git.apt, "git")

    def test_python3_package(self):
        python = get_package("python3")
        self.assertIsNotNone(python)
        self.assertEqual(python.category, "runtime")
        self.assertTrue(python.critical)

    def test_get_by_category(self):
        system_pkgs = get_packages_by_category("system")
        self.assertTrue(all(p.category == "system" for p in system_pkgs))

    def test_get_nonexistent(self):
        self.assertIsNone(get_package("nonexistent_package_123"))


class TestPackageManager(unittest.TestCase):
    def test_manager_creates(self):
        pm = PackageManager()
        self.assertIsNotNone(pm)

    def test_get_pm_name_git(self):
        pm = PackageManager()
        from installer.packages.definitions import get_package
        git = get_package("git")
        name = pm.get_pm_name(git)
        self.assertIn(name, ["git", "Git.Git", ""])


class TestVerifier(unittest.TestCase):
    def test_check_python(self):
        verifier = Verifier()
        from installer.packages.definitions import get_package
        python = get_package("python3")
        result = verifier.check_package(python)
        self.assertIsInstance(result, CheckResult)
        self.assertEqual(result.package, "python3")

    def test_verify_python_installed(self):
        verifier = Verifier()
        from installer.packages.definitions import get_package
        python = get_package("python3")
        result = verifier.check_package(python)
        self.assertTrue(result.installed)
        self.assertIsNotNone(result.path)

    def test_summary(self):
        verifier = Verifier()
        results = verifier.check_all()
        summary = verifier.summary(results)
        self.assertIn("total", summary)
        self.assertIn("installed", summary)
        self.assertIn("missing", summary)
        self.assertEqual(summary["total"], len(results))
        self.assertEqual(summary["installed"] + summary["missing"], summary["total"])


if __name__ == "__main__":
    unittest.main()
