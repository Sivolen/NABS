import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_users_permission import (
    check_allowed_device,
    get_users_group,
)


class TestDBUsersPermission(unittest.TestCase):
    @patch("app.modules.dbutils.db_users_permission.db")
    def test_check_allowed_device_true(self, mock_db):
        mock_result = [(1,)]
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = check_allowed_device([1], 100)
        self.assertTrue(result)

    @patch("app.modules.dbutils.db_users_permission.db")
    def test_check_allowed_device_false(self, mock_db):
        mock_result = []
        mock_db.session.execute.return_value.fetchall.return_value = mock_result
        result = check_allowed_device([2], 100)
        self.assertFalse(result)

    @patch("app.modules.dbutils.db_users_permission.GroupPermission")
    def test_get_users_group(self, mock_group_permission):
        mock_query = MagicMock()
        mock_group_permission.query.with_entities.return_value.filter_by.return_value = (
            mock_query
        )
        # Мокаем итерацию по результату запроса
        mock_query.__iter__.return_value = [(1, 10), (2, 20)]
        result = get_users_group(1)
        self.assertEqual(result, [10, 20])
