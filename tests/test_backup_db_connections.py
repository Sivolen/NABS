"""
TZ 7: a backup must not hold a PostgreSQL connection while it waits for a network device.

Every Nornir task runs inside `with app.app_context()`; the session of that context keeps
its connection until the context ends. The tasks therefore released nothing during the SSH
session (minutes) and the pools had to be huge. The backup now rolls the session back
(= returns the connection to the pool) before each long device operation.
"""

import unittest
from unittest.mock import MagicMock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

import backuper  # noqa: E402


def recorder():
    events = []
    db = MagicMock()
    db.session.rollback.side_effect = lambda: events.append("release-db")
    return events, db


class TestCustomBackup(unittest.TestCase):
    def run_custom(self, events, db, rollback_error=None):
        if rollback_error:
            db.session.rollback.side_effect = rollback_error
        task = MagicMock()
        task.host.name = "sw1"
        task.run.side_effect = lambda *a, **kw: (
            events.append("ssh"),
            MagicMock(result="config text"),
        )[1]
        settings = {
            "drivers_platform": "cisco_ios",
            "drivers_commands": "show run",
            "drivers_vendor": "Cisco",
            "drivers_model": "x",
        }
        with patch.object(backuper, "db", db), patch.object(
            backuper, "get_custom_driver_id", return_value=3
        ), patch.object(backuper, "get_driver_settings", return_value=settings):
            return backuper.custom_backup(task, 5, "10.0.0.1", "t")

    def test_the_connection_is_released_before_the_commands_run(self):
        events, db = recorder()
        result = self.run_custom(events, db)
        self.assertEqual(events, ["release-db", "ssh"])
        self.assertEqual(result["config"], "config text")  # the result is unchanged

    def test_every_command_runs_after_the_release(self):
        events, db = recorder()
        task = MagicMock()
        task.run.side_effect = lambda *a, **kw: (
            events.append("ssh"),
            MagicMock(result="c"),
        )[1]
        settings = {
            "drivers_platform": "p",
            "drivers_commands": "a,b,c",
            "drivers_vendor": "v",
            "drivers_model": "m",
        }
        with patch.object(backuper, "db", db), patch.object(
            backuper, "get_custom_driver_id", return_value=3
        ), patch.object(backuper, "get_driver_settings", return_value=settings):
            backuper.custom_backup(task, 5, "10.0.0.1", "t")
        self.assertEqual(events, ["release-db", "ssh", "ssh", "ssh"])

    def test_a_failing_release_does_not_break_the_backup(self):
        events, db = recorder()
        result = self.run_custom(events, db, rollback_error=RuntimeError("db hiccup"))
        self.assertEqual(events, ["ssh"])
        self.assertEqual(result["config"], "config text")


class TestBackupTask(unittest.TestCase):
    """backup_config_on_db: the outer session is released before custom / napalm backup."""

    def run_task(self, custom_driver):
        events, db = recorder()
        task = MagicMock()
        task.host.hostname = "10.0.0.1"
        task.host.name = "sw1"

        def fake_backup(**kw):
            events.append("ssh")
            return {
                "connection_status": "stop here",
                "config": "",
            }  # ends the task early

        patches = [
            patch.object(backuper, "db", db),
            patch.object(backuper, "check_ip", return_value=True),
            patch.object(backuper, "get_device_id", return_value=[5]),
            patch.object(backuper, "get_device_is_enabled", return_value=True),
            patch.object(
                backuper,
                "get_last_config_for_device",
                return_value={"last_config": "old"},
            ),
            patch.object(
                backuper, "get_driver_switch_status", return_value=custom_driver
            ),
            patch.object(backuper, "custom_backup", side_effect=fake_backup),
            patch.object(backuper, "napalm_backup", side_effect=fake_backup),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        result = backuper.backup_config_on_db(task)
        return events, result

    def test_napalm_devices(self):
        events, result = self.run_task(custom_driver=False)
        self.assertEqual(events, ["release-db", "ssh"])
        self.assertEqual(result, {"connection_status": "stop here"})

    def test_custom_driver_devices(self):
        events, result = self.run_task(custom_driver=True)
        self.assertEqual(events, ["release-db", "ssh"])

    def test_the_helper_never_raises(self):
        db = MagicMock()
        db.session.rollback.side_effect = RuntimeError("x")
        with patch.object(backuper, "db", db):
            backuper._release_db_connection()  # no exception


if __name__ == "__main__":
    unittest.main()
