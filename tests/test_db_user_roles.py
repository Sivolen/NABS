import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_user_roles import (
    create_user_role,
    delete_user_role,
    update_user_role,
    get_user_roles,
)


class TestDBUserRoles(unittest.TestCase):
    @patch("app.modules.dbutils.db_user_roles.db")
    @patch("app.modules.dbutils.db_user_roles.UserRoles")
    def test_create_user_role_success(self, mock_user_roles, mock_db):
        mock_user_roles.return_value = MagicMock()
        result = create_user_role("admin")
        self.assertTrue(result)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_user_roles.db")
    @patch("app.modules.dbutils.db_user_roles.UserRoles")
    def test_delete_user_role_success(self, mock_user_roles, mock_db):
        mock_query = MagicMock()
        mock_user_roles.query.filter_by.return_value = mock_query
        result = delete_user_role(1)
        self.assertTrue(result)
        mock_query.delete.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_user_roles.db")
    @patch("app.modules.dbutils.db_user_roles.UserRoles")
    def test_update_user_role_success(self, mock_user_roles, mock_db):
        mock_instance = MagicMock()
        mock_user_roles.query.filter_by.return_value.first.return_value = mock_instance
        result = update_user_role(1, "new_role")
        self.assertTrue(result)
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_user_roles.db")
    @patch("app.modules.dbutils.db_user_roles.UserRoles")
    def test_get_user_roles(self, mock_user_roles, mock_db):
        mock_roles = [
            MagicMock(id=1, role_name="admin"),
            MagicMock(id=2, role_name="user"),
        ]
        mock_user_roles.query.order_by.return_value = mock_roles
        result = get_user_roles()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role_name"], "admin")
