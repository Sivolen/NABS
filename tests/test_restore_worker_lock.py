"""Restore must wait for backup and hold its device lock during every operation."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.backup_lock import device_backup_lock
from app.modules.restore.worker import RestoreWorker


class TestRestoreBackupCoordination(unittest.TestCase):
    def setUp(self):
        self.engine = Mock()
        self.store = Mock()
        self.store.list_jobs.return_value = []
        self.store.list_requested.return_value = []
        self.worker = RestoreWorker(self.engine, self.store, "test")
        self.job = SimpleNamespace(id=51, device_id=987650)

    def assert_device_is_locked(self, *args):
        with device_backup_lock(self.job.device_id) as acquired:
            self.assertFalse(acquired)
        with device_backup_lock(self.job.device_id + 1) as acquired:
            self.assertTrue(acquired)

    def test_precheck_waits_without_losing_its_request(self):
        self.store.list_requested.return_value = [self.job]
        with device_backup_lock(self.job.device_id) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.worker.run_once(), 0)
        self.engine.run_precheck.assert_not_called()
        self.engine.run_precheck.side_effect = self.assert_device_is_locked
        self.assertEqual(self.worker.run_once(), 1)
        self.engine.run_precheck.assert_called_once_with(self.job.id)

    def test_execute_waits_and_holds_the_same_lock_as_backup(self):
        self.store.list_jobs.return_value = [self.job]
        with device_backup_lock(self.job.device_id):
            self.assertEqual(self.worker.run_once(), 0)
        self.engine.execute.assert_not_called()
        self.engine.execute.side_effect = self.assert_device_is_locked
        self.assertEqual(self.worker.run_once(), 1)
        self.engine.execute.assert_called_once_with(self.job.id, "test")

    def test_failed_operation_releases_the_lock(self):
        self.store.list_jobs.return_value = [self.job]
        self.engine.execute.side_effect = RuntimeError("simulated failure")
        with self.assertLogs("nabs.restore.worker", "ERROR"):
            self.assertEqual(self.worker.run_once(), 0)
        with device_backup_lock(self.job.device_id) as acquired:
            self.assertTrue(acquired)


if __name__ == "__main__":
    unittest.main()
