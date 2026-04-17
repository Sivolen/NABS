import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_users import get_notification_recipients


class TestDBUsers(unittest.TestCase):
    @patch("app.modules.dbutils.db_users.Users")
    def test_get_notification_recipients(self, mock_users):
        mock_users.query.filter_by.return_value.all.return_value = [
            MagicMock(email="user1@example.com"),
            MagicMock(email="user2@example.com"),
        ]
        result = get_notification_recipients()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "user1@example.com")
