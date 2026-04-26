import os
import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_groups import (
    del_device_group,
    update_device_group,
    get_all_devices_group,
)
from app.modules.dbutils.db_users_permission import get_users_group

os.environ["FLASK_ENV"] = "testing"


class TestDBGroups(unittest.TestCase):
    @patch("app.modules.dbutils.db_users_permission.GroupPermission")
    def test_get_users_group(self, mock_group_permission):
        mock_query = MagicMock()
        mock_group_permission.query.with_entities.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        # Мокаем итерацию по объекту запроса
        mock_query.__iter__.return_value = [(1, 10), (2, 20)]
        result = get_users_group(1)
        self.assertEqual(result, [10, 20])

    @patch("app.modules.dbutils.db_groups.db")
    @patch("app.modules.dbutils.db_groups.DevicesGroup")
    def test_del_device_group_success(self, mock_devices_group, mock_db):
        mock_query = MagicMock()
        mock_devices_group.query.filter_by.return_value = mock_query
        result = del_device_group(1)
        self.assertTrue(result)
        mock_query.delete.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_groups.db")
    @patch("app.modules.dbutils.db_groups.DevicesGroup")
    def test_update_device_group_success(self, mock_group, mock_db):
        mock_instance = MagicMock()
        mock_group.query.filter_by.return_value.first.return_value = mock_instance
        result = update_device_group(1, "new_name")
        self.assertTrue(result)
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_groups.db")
    @patch("app.modules.dbutils.db_groups.DevicesGroup")
    def test_get_all_devices_group(self, mock_group, mock_db):
        mock_groups = [
            MagicMock(id=1, group_name="group1"),
            MagicMock(id=2, group_name="group2"),
        ]
        mock_group.query.order_by.return_value = mock_groups
        result = get_all_devices_group()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["group_name"], "group1")
