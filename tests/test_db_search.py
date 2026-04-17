import unittest
from unittest.mock import patch, MagicMock
from app.modules.dbutils.db_search import search_in_db
from types import SimpleNamespace


class TestDBSearch(unittest.TestCase):
    @patch("app.modules.dbutils.db_search.db")
    def test_search_in_db_success(self, mock_db):
        # Создаём объект с нужными атрибутами вместо кортежа
        mock_row = SimpleNamespace(
            id=1,
            device_ip="10.0.0.1",
            device_id=100,
            timestamp="2024-01-01 12:00",
            config_snippet="line1\nline2\nline3",
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.session.execute.return_value = mock_result

        result = search_in_db("test", 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["device_ip"], "10.0.0.1")
