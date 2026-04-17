import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_drivers import add_driver, get_all_drivers


class TestDBDrivers(unittest.TestCase):
    @patch("app.modules.dbutils.db_drivers.db")
    @patch("app.modules.dbutils.db_drivers.CustomDrivers")
    def test_add_driver_success(self, mock_custom_drivers, mock_db):
        mock_custom_drivers.return_value = MagicMock()
        result = add_driver("test", "Cisco", "2960", "ios", "show run")
        self.assertTrue(result)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_drivers.db")
    @patch("app.modules.dbutils.db_drivers.CustomDrivers")
    def test_add_driver_failure(self, mock_custom_drivers, mock_db):
        mock_db.session.commit.side_effect = Exception("DB error")
        result = add_driver("test", "Cisco", "2960", "ios", "show run")
        self.assertFalse(result)
        mock_db.session.rollback.assert_called_once()
