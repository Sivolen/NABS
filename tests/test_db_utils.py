import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_utils import write_config


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
