"""Tests for the self-healing paths: escalating system-package repairs and
doctor auto-fixes. Never invokes a real package manager or the network."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installer import operations
from installer.core import config as cfgmod, state as statemod
from installer.core.packages import PackageRegistry
from installer.doctor import Doctor
from installer.version import INSTALLER_NAME

GHOST = "definitely-not-a-real-tool-xyz"


def _ghost_registry():
    return PackageRegistry.from_dict({
        "packages": {
            "ghosttool": {"verify": GHOST, "systems": {"apt": ["ghosttool"]}},
        }
    })


class RepairLadderTests(unittest.TestCase):
    def test_without_heal_falls_back_to_install(self):
        calls = []

        class FakeManager:
            name = "apt"

            def install(self, packages, dry_run=False):
                calls.append(list(packages))
                return True

        registry = _ghost_registry()
        still = operations.repair_system_packages(FakeManager(), registry, ["ghosttool"])
        # A plain install is attempted, but the fake can't restore the binary.
        self.assertEqual(still, ["ghosttool"])
        self.assertEqual(calls, [["ghosttool"]])

    def test_ladder_escalates_when_heal_leaves_missing(self):
        calls = []

        class FakeManager:
            name = "apt"

            def heal(self, packages, dry_run=False):
                calls.append("heal")
                return True

            def purge_and_reinstall(self, packages, dry_run=False):
                calls.append("purge_and_reinstall")
                return True

            def install(self, packages, dry_run=False):
                calls.append("install")
                return True

        registry = _ghost_registry()
        still = operations.repair_system_packages(FakeManager(), registry, ["ghosttool"])
        # Binary never appears, so every step of the ladder runs and the tool
        # is still reported missing.
        self.assertEqual(still, ["ghosttool"])
        self.assertEqual(calls, ["heal", "purge_and_reinstall", "install"])

    def test_stops_as_soon_as_binary_returns(self):
        with tempfile.TemporaryDirectory() as td:
            bin_dir = Path(td)
            calls = []

            class FakeManager:
                name = "apt"

                def heal(self, packages, dry_run=False):
                    calls.append("heal")
                    exe = bin_dir / GHOST
                    exe.write_text("#!/bin/sh\necho ghost 9.9\n")
                    exe.chmod(0o755)
                    return True

                def purge_and_reinstall(self, packages, dry_run=False):
                    calls.append("purge_and_reinstall")
                    return True

                def install(self, packages, dry_run=False):
                    calls.append("install")
                    return True

            with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}):
                still = operations.repair_system_packages(
                    FakeManager(), _ghost_registry(), ["ghosttool"])
            self.assertEqual(still, [])
            self.assertEqual(calls, ["heal"])

    def test_installed_tool_needs_no_repair(self):
        class FakeManager:
            name = "apt"

            def heal(self, packages, dry_run=False):
                self.called = True
                return True

        # "python3" is present on any machine running the tests.
        registry = PackageRegistry.from_dict({
            "packages": {"pytool": {"verify": "python3", "systems": {"apt": ["python3"]}}},
        })
        m = FakeManager()
        still = operations.repair_system_packages(m, registry, ["pytool"])
        self.assertEqual(still, [])
        self.assertFalse(getattr(m, "called", False))


class DoctorFixDetectionTests(unittest.TestCase):
    def test_corrupt_config_gets_regeneration_fix(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "config.json").write_text("{not valid json")
            store = cfgmod.ConfigStore(INSTALLER_NAME, "config.json", "json", base)
            doc = Doctor(store, base, PackageRegistry.from_dict({"packages": {}}))
            doc._check_config()
            check = doc.checks[0]
            self.assertFalse(check.ok)
            self.assertIsNotNone(check.fix)
            self.assertTrue(check.fix())
            self.assertIsInstance(store.load(), cfgmod.Config)

    def test_failed_stage_surfaces_repair_fix(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            st = statemod.InstallState.load(base)
            st.begin_stage("copy_source")
            st.end_stage("copy_source", "failed", "boom")
            st.save()
            store = cfgmod.ConfigStore(INSTALLER_NAME, "config.json", "json", base)
            doc = Doctor(store, base, PackageRegistry.from_dict({"packages": {}}))
            doc._check_state()
            check = doc.checks[0]
            self.assertFalse(check.ok)
            self.assertIn("failed stages", check.detail)
            self.assertIsNotNone(check.fix)

    def test_healthy_state_no_fix(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            st = statemod.InstallState.load(base)
            st.mark_installed("1.1.0")
            st.save()
            store = cfgmod.ConfigStore(INSTALLER_NAME, "config.json", "json", base)
            doc = Doctor(store, base, PackageRegistry.from_dict({"packages": {}}))
            doc._check_state()
            check = doc.checks[0]
            self.assertTrue(check.ok)
            self.assertIsNone(check.fix)


if __name__ == "__main__":
    unittest.main()
