import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_dashboards import (
    get_devices_count,
    get_models_count,
    get_configs_count,
    get_error_connections_limit,
    get_statistic,
)

class TestDBDashboards(unittest.TestCase):
    @patch('app.modules.dbutils.db_dashboards.db')
    def test_get_devices_count(self, mock_db):
        mock_result = [
            ('Cisco', 10),
            ('Huawei', 5),
            ('Total', 15)
        ]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = get_devices_count(1)
        self.assertEqual(result['Cisco'], 10)
        self.assertEqual(result['Huawei'], 5)
        self.assertEqual(result['Total'], 15)

    @patch('app.modules.dbutils.db_dashboards.db')
    def test_get_models_count(self, mock_db):
        mock_result = [
            ('Cisco 2960', 8),
            ('Huawei CE6850', 4),
            ('Total', 12)
        ]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = get_models_count(1)
        self.assertEqual(result['Cisco 2960'], 8)
        self.assertEqual(result['Huawei CE6850'], 4)

    @patch('app.modules.dbutils.db_dashboards.db')
    def test_get_configs_count(self, mock_db):
        mock_result = [
            ('sw1', 20),
            ('sw2', 15),
            ('Total', 35)
        ]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = get_configs_count(1)
        self.assertEqual(result['sw1'], 20)
        self.assertEqual(result['sw2'], 15)

    @patch('app.modules.dbutils.db_dashboards.db')
    def test_get_error_connections_limit(self, mock_db):
        mock_result = [
            ('Connection timeout', 1, '10.0.0.1', 'sw1', 'Cisco', '2024-01-01 12:00'),
            ('Auth failed', 2, '10.0.0.2', 'sw2', 'Huawei', '2024-01-01 12:05')
        ]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = get_error_connections_limit(1)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['connection_status'], 'Connection timeout')
        self.assertEqual(result[0]['device_ip'], '10.0.0.1')

    @patch('app.modules.dbutils.db_dashboards.db')
    def test_get_statistic(self, mock_db):
        mock_result = [
            (datetime(2024, 1, 1), 5),
            (datetime(2024, 2, 1), 7),
            (datetime(2024, 3, 1), 3)
        ]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = get_statistic(1)
        self.assertEqual(len(result), 3)
        self.assertEqual(result, [5, 7, 3])