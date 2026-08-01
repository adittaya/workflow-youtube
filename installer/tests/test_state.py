"""Tests for state machine and rollback journal."""

import tempfile
import unittest
from pathlib import Path

from installer.core import state as statemod
from installer import rollback as rollmod


class StateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.st = statemod.InstallState.load(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_initial_state(self):
        self.assertFalse(self.st.is_installed())
        self.assertEqual(self.st.completed_stages(), [])

    def test_stage_lifecycle(self):
        self.st.begin_stage("copy_source")
        self.assertEqual(self.st.stage_status("copy_source"), statemod.IN_PROGRESS)
        self.st.end_stage("copy_source", "done")
        self.assertEqual(self.st.stage_status("copy_source"), statemod.DONE)
        self.assertEqual(self.st.completed_stages(), ["copy_source"])

    def test_failed_stage_detected_by_repair(self):
        self.st.begin_stage("config")
        self.st.end_stage("config", "failed", "boom")
        self.assertEqual(self.st.needs_repair(), ["config"])

    def test_mark_installed_persists(self):
        self.st.mark_installed("1.0.0")
        self.st.save()
        reloaded = statemod.InstallState.load(self.dir)
        self.assertTrue(reloaded.is_installed())
        self.assertEqual(reloaded.meta("installed_version"), "1.0.0")


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.journal = rollmod.RollbackJournal(self.dir / "rollback.json").load()

    def tearDown(self):
        self._tmp.cleanup()

    def test_remove_undo(self):
        f = self.dir / "created.txt"
        f.write_text("data")
        self.journal.record_remove(f, "created file")
        executed = self.journal.rollback()
        self.assertFalse(f.exists())
        self.assertTrue(any("created.txt" in e for e in executed))

    def test_restore_undo(self):
        f = self.dir / "config.json"
        f.write_text("original")
        snapshot = f.read_text()
        self.journal.record_restore(f, snapshot, "config write")
        f.write_text("modified")
        self.journal.rollback()
        self.assertEqual(f.read_text(), "original")

    def test_persistence(self):
        self.journal.record_remove(self.dir / "a.txt", "a")
        self.journal.persist()
        reloaded = rollmod.RollbackJournal(self.dir / "rollback.json").load()
        self.assertEqual(len(reloaded), 1)

    def test_clear(self):
        self.journal.record_remove(self.dir / "a.txt", "a")
        self.journal.clear()
        self.assertEqual(len(self.journal), 0)


if __name__ == "__main__":
    unittest.main()
