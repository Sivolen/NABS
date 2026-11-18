"""Exercise both entry points through real Nornir tasks with fake network I/O."""

import importlib
import logging
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nornir.core import Nornir
from nornir.core.inventory import Host, Inventory
from nornir.plugins.runners import SerialRunner
from netmiko import ReadTimeout

import backuper
from app.modules import backup_service as service
from app.modules.validators import encode_driver_commands


class TestSharedBackup(unittest.TestCase):
    def run_backup(
        self,
        mode,
        *,
        custom=False,
        reference=None,
        saved=True,
        read_error=None,
        retry=False
    ):
        host = Host(
            name="723",
            hostname="192.0.2.23",
            platform="ios",
            data={"display_name": "lab-switch"},
        )
        connection = MagicMock()
        connection.connection = connection
        outputs = (
            ["short", "hostname lab-switch\ninterface Loopback0"]
            if retry
            else ["hostname lab-switch\ninterface Loopback0"]
        )
        if read_error:
            connection.get_config.side_effect = read_error
            connection.send_command.side_effect = read_error
        else:
            connection.get_config.side_effect = [
                {"running": value} for value in outputs
            ]
            connection.send_command.return_value = outputs[-1]
        connection.get_facts.return_value = {"vendor": "Cisco", "model": "Lab"}
        host.connections["netmiko" if custom else "napalm"] = connection
        inventory = Nornir(
            inventory=Inventory(hosts={host.name: host}), runner=SerialRunner()
        )
        stored = MagicMock(return_value=saved)
        status = MagicMock()
        environment = MagicMock()
        validation = MagicMock()
        device = SimpleNamespace(device_ip=host.hostname, is_enabled=True)

        with ExitStack() as patches:
            mocks = {
                "get_device_id": MagicMock(return_value=(723,)),
                "get_device_is_enabled": MagicMock(return_value=True),
                "get_driver_switch_status": MagicMock(return_value=custom),
                "get_last_config_for_device": MagicMock(return_value=reference),
                "get_custom_driver_id": MagicMock(return_value=5),
                "get_driver_settings": MagicMock(
                    return_value={
                        "drivers_platform": "cisco_ios",
                        "drivers_vendor": "Cisco",
                        "drivers_model": "Lab",
                        "drivers_commands": encode_driver_commands(
                            '["terminal length 0"]', "show running-config"
                        ),
                    }
                ),
                "write_config": stored,
                "update_device_env": environment,
                "update_device_status": status,
                "run_validation": validation,
                "config_sanity_retry_delay": 0,
            }
            patches.enter_context(patch.multiple(service, **mocks))
            patches.enter_context(patch.object(service, "db"))
            service.db.session.get.return_value = device
            patches.enter_context(
                patch.object(
                    service.Helpers, "nornir_driver_sql", return_value=inventory
                )
            )
            if mode == "single":
                result = service.backup_device(723)
            else:
                with inventory:
                    aggregate = inventory.run(task=backuper.backup_config_on_db)
                    result = aggregate["723"][0].result
            self.assertFalse(
                host.connections, "Nornir must close connections on success and error"
            )
        return result, stored, status, environment, validation, connection

    def test_first_backup_is_identical_for_both_drivers_and_entry_points(self):
        for mode in ("single", "bulk"):
            for custom in (False, True):
                with self.subTest(mode=mode, custom=custom):
                    result, stored, _, _, validation, connection = self.run_backup(
                        mode, custom=custom
                    )
                    self.assertEqual(result["connection_status"], "Ok")
                    self.assertTrue(result["first_backup"])
                    self.assertFalse(result["changed"])
                    self.assertEqual(result["hostname"], "lab-switch")
                    self.assertEqual(
                        stored.call_args.kwargs["config"],
                        "hostname lab-switch\ninterface Loopback0",
                    )
                    validation.assert_called_once()
                    if custom:
                        self.assertEqual(
                            [
                                call.args[0]
                                for call in connection.send_command.call_args_list
                            ],
                            ["terminal length 0", "show running-config"],
                        )

    def test_unchanged_and_failed_save_match_in_both_modes(self):
        for mode in ("single", "bulk"):
            with self.subTest(mode=mode, case="unchanged"):
                result, stored, _, _, validation, _ = self.run_backup(
                    mode,
                    reference={
                        "last_config": "hostname lab-switch\ninterface Loopback0",
                        "timestamp": "previous",
                    },
                )
                self.assertEqual(result["connection_status"], "Ok")
                self.assertFalse(result["changed"])
                stored.assert_not_called()
                validation.assert_called_once()
            with self.subTest(mode=mode, case="failed-save"):
                result, stored, status, environment, validation, _ = self.run_backup(
                    mode, saved=False
                )
                self.assertEqual(
                    result["connection_status"], "Could not save configuration"
                )
                stored.assert_called_once()
                status.assert_called_once()
                environment.assert_not_called()
                validation.assert_not_called()

    def test_netmiko_timeout_is_the_current_error_in_both_modes(self):
        for mode in ("single", "bulk"):
            with self.subTest(mode=mode):
                result, stored, status, _, _, _ = self.run_backup(
                    mode, custom=True, read_error=ReadTimeout("fixture read timed out")
                )
                self.assertIn("ReadTimeout", result["connection_status"])
                self.assertIn("fixture read timed out", result["connection_status"])
                stored.assert_not_called()
                status.assert_called()

    def test_short_response_is_retried_before_saving_in_both_modes(self):
        previous = "\n".join("old" for _ in range(20))
        with patch.object(service, "config_sanity_min_ratio", 0.1):
            for mode in ("single", "bulk"):
                with self.subTest(mode=mode):
                    result, stored, _, _, _, connection = self.run_backup(
                        mode, reference={"last_config": previous}, retry=True
                    )
                    self.assertEqual(connection.get_config.call_count, 2)
                    self.assertEqual(result["connection_status"], "Ok")
                    stored.assert_called_once()

    def test_root_and_service_export_the_same_task(self):
        self.assertIs(backuper.backup_config_on_db, service.backup_config_on_db)

    def test_legacy_request_cannot_choose_the_driver(self):
        with patch.object(service, "get_device_id", return_value=(723,)), patch.object(
            service, "backup_device", return_value={"connection_status": "Ok"}
        ) as backup:
            service.run_backup_config_on_db(
                {"device": "192.0.2.23", "driver": "untrusted"}
            )
        backup.assert_called_once_with(723)


class TestSchedulerEntryPoint(unittest.TestCase):
    def test_scheduled_backup_calls_the_bulk_entry_point(self):
        with patch("logging.FileHandler", return_value=logging.NullHandler()):
            runner = importlib.import_module("scheduler_runner")
        with patch.object(backuper, "run_backup") as run:
            runner.scheduled_backup()
        run.assert_called_once_with()
