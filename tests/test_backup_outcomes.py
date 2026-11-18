import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules import backup_service as service


class TestBackupOutcomes(unittest.TestCase):
    def call_backup(self, candidate, *, saved=True, reference="old config"):
        mocks = {
            "update_device_status": MagicMock(),
            "write_config": MagicMock(return_value=saved),
            "update_device_env": MagicMock(),
            "get_device_is_enabled": MagicMock(return_value=True),
            "get_driver_switch_status": MagicMock(return_value=False),
            "get_last_config_for_device": MagicMock(
                return_value={"last_config": reference}
            ),
            "napalm_backup": MagicMock(
                return_value={
                    "connection_status": "Ok",
                    "vendor": "Cisco",
                    "model": "Lab",
                    "config": candidate,
                }
            ),
        }
        with patch.multiple(service, **mocks):
            task = SimpleNamespace(
                host=SimpleNamespace(platform="ios", name="lab", data={})
            )
            with patch.object(service, "_release_db_connection"):
                result = service._backup_device(task, "192.0.2.1", 123, "t")
        return result, mocks

    def test_failed_save_never_marks_backup_successful(self):
        result, mocks = self.call_backup("changed config", saved=False)
        self.assertEqual(result["connection_status"], "Could not save configuration")
        mocks["update_device_env"].assert_not_called()
        mocks["update_device_status"].assert_called_once()

    def test_no_empty_result_is_saved(self):
        for empty in ("", "  \n ", None):
            with self.subTest(empty=empty):
                result, mocks = self.call_backup(empty)
                self.assertNotEqual(result["connection_status"], "Ok")
                mocks["write_config"].assert_not_called()
