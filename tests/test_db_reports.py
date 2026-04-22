import os
import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_reports import get_error_connections

os.environ["FLASK_ENV"] = "testing"


class TestDBReports(unittest.TestCase):
    @patch("app.modules.dbutils.db_reports.db")
    def test_get_error_connections(self, mock_db):
        mock_result = [
            ("Connection timeout", 1, "10.0.0.1", "sw1", "Cisco", "2024-01-01 12:00"),
            ("Auth failed", 2, "10.0.0.2", "sw2", "Huawei", "2024-01-01 12:05"),
        ]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = get_error_connections(1)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["connection_status"], "Connection timeout")
        self.assertEqual(result[0]["device_ip"], "10.0.0.1")
        self.assertEqual(result[1]["device_hostname"], "sw2")
