import os
import unittest
from unittest.mock import patch
from app import app

os.environ["FLASK_ENV"] = "testing"


class TestViews(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    @patch("app.views.scheduler.get_scheduler_full_status")
    def test_scheduler_status_api(self, mock_status):
        mock_status.return_value = {"enabled": True, "running": True, "active": True}
        # Нужно имитировать авторизованную сессию
        with self.app.session_transaction() as sess:
            sess["user"] = "test@example.com"
            sess["rights"] = "sadmin"
            sess["user_id"] = 1
        response = self.app.get("/api/scheduler_status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["active"])
