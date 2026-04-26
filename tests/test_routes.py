import os
import unittest
from app import app

os.environ["FLASK_ENV"] = "testing"


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        # Создаём сессию админа
        with self.app.session_transaction() as sess:
            sess["user"] = "admin@example.com"
            sess["rights"] = "sadmin"
            sess["user_id"] = 1

    def test_devices_page(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Devices", response.data)

    def test_dashboards_page(self):
        response = self.app.get("/dashboards/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard", response.data)

    def test_scheduler_page(self):
        response = self.app.get("/scheduler/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Scheduler", response.data)

    def test_api_scheduler_status(self):
        response = self.app.get("/api/scheduler_status")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"active", response.data)

    def test_login_redirect(self):
        # Выходим из сессии
        with self.app.session_transaction() as sess:
            sess.clear()
        response = self.app.get("/devices/", follow_redirects=True)
        self.assertIn(b"Login", response.data)
