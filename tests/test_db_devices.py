import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_devices import get_device_id, get_devices_by_rights, get_devices_env


class TestDBDevices(unittest.TestCase):
    @patch("app.modules.dbutils.db_devices.Devices")
    def test_get_device_id_found(self, mock_devices):
        mock_devices.query.with_entities.return_value.filter_by.return_value.first.return_value = (
            1,
        )
        result = get_device_id("10.0.0.1")
        self.assertEqual(result, (1,))

    @patch("app.modules.dbutils.db_devices.Devices")
    def test_get_device_id_not_found(self, mock_devices):
        mock_devices.query.with_entities.return_value.filter_by.return_value.first.return_value = (
            None
        )
        result = get_device_id("10.0.0.2")
        self.assertIsNone(result)

    class TestDBDevicesExtended(unittest.TestCase):
        @patch('app.modules.dbutils.db_devices.db')
        def test_get_devices_by_rights(self, mock_db):
            mock_rows = [
                (1, '10.0.0.1', 'sw1', 'Cisco', '2960', 'Ok', 'ios', '2024-01-01', 2, 'group1', '2024-01-02')
            ]
            mock_db.session.execute.return_value.fetchall.return_value = mock_rows
            result = get_devices_by_rights(1)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['device_ip'], '10.0.0.1')
            self.assertEqual(result[0]['hostname'], 'sw1')
            self.assertTrue(result[0]['check_previous_config'])

        @patch('app.modules.dbutils.db_devices.db')
        def test_get_devices_env(self, mock_db):
            mock_rows = [
                ('group1', 1, '10.0.0.1', 'sw1', 'Cisco', '2960', 'Ok', 'ios', '2024-01-01', 2, '2024-01-02')
            ]
            mock_db.session.execute.return_value.fetchall.return_value = mock_rows
            result = get_devices_env()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['device_ip'], '10.0.0.1')
            self.assertTrue(result[0]['check_previous_config'])