import os
import unittest
from unittest.mock import MagicMock, patch
from backuper import backup_config_on_db

os.environ["FLASK_ENV"] = "testing"


class TestBackuper(unittest.TestCase):
    @patch("backuper.get_device_id")
    @patch("backuper.get_device_is_enabled")
    @patch("backuper.get_driver_switch_status")
    @patch("backuper.napalm_backup")
    @patch("backuper.update_device_env")
    @patch("backuper.get_last_config_for_device")
    @patch("backuper.write_config")
    @patch("backuper.diff_changed")
    @patch("backuper.get_diff_summary")
    def test_backup_with_change(
        self,
        mock_get_diff_summary,
        mock_diff_changed,
        mock_write_config,
        mock_get_last_config,
        mock_update_device_env,
        mock_napalm_backup,
        mock_driver_switch,
        mock_device_enabled,
        mock_device_id,
    ):
        # Настройка моков
        mock_task = MagicMock()
        mock_task.host.hostname = "10.0.0.1"

        mock_device_id.return_value = (1,)
        mock_device_enabled.return_value = True
        mock_driver_switch.return_value = False
        mock_napalm_backup.return_value = {
            "vendor": "Cisco",
            "model": "2960",
            "config": "new config",
        }
        mock_get_last_config.return_value = {"last_config": "old config"}
        mock_diff_changed.return_value = False  # конфиги разные
        mock_get_diff_summary.return_value = ("diff line1\ndiff line2", False)

        # Вызов функции
        result = backup_config_on_db(mock_task)

        # Проверки
        self.assertIsNotNone(result)
        self.assertTrue(result["changed"])
        self.assertEqual(result["ip"], "10.0.0.1")
        mock_write_config.assert_called_once()

    @patch("backuper.get_device_id")
    @patch("backuper.get_device_is_enabled")
    @patch("backuper.get_driver_switch_status")
    @patch("backuper.napalm_backup")
    @patch("backuper.update_device_env")
    @patch("backuper.get_last_config_for_device")
    @patch("backuper.write_config")
    @patch("backuper.diff_changed")
    def test_backup_without_change(
        self,
        mock_diff_changed,
        mock_write_config,
        mock_get_last_config,
        mock_update_device_env,
        mock_napalm_backup,
        mock_driver_switch,
        mock_device_enabled,
        mock_device_id,
    ):
        mock_task = MagicMock()
        mock_task.host.hostname = "10.0.0.1"

        mock_device_id.return_value = (1,)
        mock_device_enabled.return_value = True
        mock_driver_switch.return_value = False
        mock_napalm_backup.return_value = {
            "vendor": "Cisco",
            "model": "2960",
            "config": "same config",
        }
        mock_get_last_config.return_value = {"last_config": "same config"}
        mock_diff_changed.return_value = True  # конфиги одинаковые

        result = backup_config_on_db(mock_task)

        self.assertIsNotNone(result)
        self.assertFalse(result["changed"])
        mock_write_config.assert_not_called()

    @patch("backuper.get_custom_driver_id")
    @patch("backuper.get_driver_settings")
    @patch("backuper.netmiko_send_command")
    def test_custom_backup_success(
        self, mock_netmiko, mock_driver_settings, mock_custom_id
    ):
        from backuper import custom_backup

        mock_custom_id.return_value = 1
        mock_driver_settings.return_value = {
            "drivers_platform": "cisco_ios",
            "drivers_vendor": "Cisco",
            "drivers_model": "2960",
            "drivers_commands": "show version,show running-config",
        }
        mock_task = MagicMock()
        mock_task.run.return_value.result = "config data"

        result = custom_backup(mock_task, 1, "10.0.0.1", "2024-01-01 00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["vendor"], "Cisco")
        self.assertEqual(result["config"], "config data")
        self.assertEqual(mock_task.run.call_count, 2)

    @patch("napalm.get_network_driver")
    @patch("app.modules.dbutils.db_utils.get_user_and_pass")
    @patch("backuper.update_device_status")
    def test_napalm_backup_success(
        self, mock_update_status, mock_get_auth, mock_get_driver
    ):
        from backuper import napalm_backup

        mock_task = MagicMock()
        mock_task.run.return_value.result = {
            "get_facts": {"vendor": "Cisco", "model": "2960"},
            "config": {"running": "running config"},
        }
        mock_get_auth.return_value = {
            "credentials_username": "user",
            "credentials_password": "encrypted",
            "ssh_port": 22,
        }
        mock_device = MagicMock()
        mock_device.open = MagicMock()
        mock_device.get_facts.return_value = {"vendor": "Cisco", "model": "2960"}
        mock_device.get_config.return_value = {"running": "running config"}
        mock_get_driver.return_value.return_value = mock_device

        result = napalm_backup(mock_task, 1, "10.0.0.1", "2024-01-01 00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["vendor"], "Cisco")
        self.assertEqual(result["config"], "running config")


if __name__ == "__main__":
    unittest.main()
