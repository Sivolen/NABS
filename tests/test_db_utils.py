import os
import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_utils import write_config, get_previous_config

os.environ["FLASK_ENV"] = "testing"


class TestDBUtils(unittest.TestCase):
    @patch("app.modules.dbutils.db_utils.get_device_id")
    @patch("app.modules.dbutils.db_utils.Configs")
    @patch("app.modules.dbutils.db_utils.db")
    def test_write_config_success(self, mock_db, mock_configs, mock_get_device_id):
        mock_get_device_id.return_value = (1,)
        mock_config_entry = MagicMock()
        mock_configs.return_value = mock_config_entry
        result = write_config("10.0.0.1", "config text", "2024-01-01 00:00")
        self.assertTrue(result)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_utils.Configs")
    def test_get_previous_config_found(self, mock_configs):
        entry = MagicMock(id=5, device_config="cfg", timestamp="2026-01-01 10:00")
        query = mock_configs.query.order_by.return_value.filter_by.return_value
        query.first.return_value = entry
        result = get_previous_config(1, "2026-01-01 10:00")
        self.assertEqual(
            result,
            {"id": 5, "device_config": "cfg", "timestamp": "2026-01-01 10:00"},
        )

    @patch("app.modules.dbutils.db_utils.Configs")
    def test_get_previous_config_missing_returns_none(self, mock_configs):
        query = mock_configs.query.order_by.return_value.filter_by.return_value
        query.first.return_value = None
        self.assertIsNone(get_previous_config(1, "2020-01-01 00:00"))
