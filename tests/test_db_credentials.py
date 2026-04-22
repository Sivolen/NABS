import os
import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_credentials import (
    add_credentials,
    update_credentials,
)

os.environ["FLASK_ENV"] = "testing"


class TestDBCredentials(unittest.TestCase):
    @patch("app.modules.dbutils.db_credentials.db")
    @patch("app.modules.dbutils.db_credentials.Credentials")
    def test_add_credentials_success(self, mock_credentials, mock_db):
        mock_credentials.return_value = MagicMock()
        result = add_credentials("test", "user", "pass", 1)
        self.assertTrue(result)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_credentials.db")
    def test_add_credentials_failure(self, mock_db):
        mock_db.session.commit.side_effect = Exception("DB error")
        result = add_credentials("test", "user", "pass", 1)
        self.assertFalse(result)
        mock_db.session.rollback.assert_called_once()

    @patch("app.modules.dbutils.db_credentials.db")
    @patch("app.modules.dbutils.db_credentials.Credentials")
    def test_update_credentials_success(self, mock_credentials, mock_db):
        mock_instance = MagicMock()
        mock_credentials.query.filter_by.return_value.first.return_value = mock_instance
        result = update_credentials(1, "new_name", "new_user", "new_pass", 2)
        self.assertTrue(result)
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_credentials.db")
    def test_update_credentials_failure(self, mock_db):
        mock_query = MagicMock()
        mock_db.session.query.return_value = mock_query
        mock_query.filter_by.return_value.first.return_value = None
        result = update_credentials(1, "new_name", "new_user", "new_pass", 2)
        self.assertIsNone(result)
