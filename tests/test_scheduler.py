import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from app.modules.scheduler_manager import is_scheduler_running, get_scheduler_status
from app.modules.dbutils.db_scheduler import (
    update_scheduler_heartbeat,
)

os.environ["FLASK_ENV"] = "testing"


class TestScheduler(unittest.TestCase):
    @patch("app.modules.scheduler_manager.get_scheduler_heartbeat")
    def test_is_scheduler_running_recent_heartbeat(self, mock_get_heartbeat):
        mock_get_heartbeat.return_value = {
            "last_seen": datetime.now(timezone.utc) - timedelta(seconds=30),
            "status": "running",
        }
        self.assertTrue(is_scheduler_running())

    @patch("app.modules.scheduler_manager.get_scheduler_heartbeat")
    def test_is_scheduler_running_old_heartbeat(self, mock_get_heartbeat):
        mock_get_heartbeat.return_value = {
            "last_seen": datetime.now(timezone.utc) - timedelta(minutes=5),
            "status": "running",
        }
        self.assertFalse(is_scheduler_running())

    @patch("app.modules.scheduler_manager.get_scheduler_heartbeat")
    def test_is_scheduler_running_no_heartbeat(self, mock_get_heartbeat):
        mock_get_heartbeat.return_value = None
        self.assertFalse(is_scheduler_running())

    @patch("app.modules.dbutils.db_scheduler.SchedulerHeartbeat")
    @patch("app.modules.dbutils.db_scheduler.db")
    def test_update_scheduler_heartbeat_creates(self, mock_db, mock_heartbeat_cls):
        mock_heartbeat_cls.query.first.return_value = None
        mock_heartbeat_instance = MagicMock()
        mock_heartbeat_cls.return_value = mock_heartbeat_instance

        result = update_scheduler_heartbeat()
        self.assertTrue(result)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()
        mock_heartbeat_instance.last_seen is not None
        mock_heartbeat_instance.status = "running"

    @patch("app.modules.dbutils.db_scheduler.SchedulerSettings")
    def test_get_scheduler_settings(self, mock_settings):
        mock_settings.query.first.return_value = MagicMock(
            is_enabled=True, trigger_type="interval", interval_seconds=3600
        )
        from app.modules.dbutils.db_scheduler import get_scheduler_settings

        settings = get_scheduler_settings()
        self.assertIsNotNone(settings)
        self.assertTrue(settings.is_enabled)

    @patch("app.modules.dbutils.db_scheduler.SchedulerSettings")
    @patch("app.modules.dbutils.db_scheduler.db")
    def test_update_scheduler_settings_create(self, mock_db, mock_settings_cls):
        from app.modules.dbutils.db_scheduler import update_scheduler_settings

        mock_settings_cls.query.first.return_value = None
        mock_instance = MagicMock()
        mock_settings_cls.return_value = mock_instance
        result = update_scheduler_settings(True, "interval", 3600, "")
        self.assertTrue(result)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()
        self.assertEqual(mock_instance.is_enabled, True)
        self.assertEqual(mock_instance.trigger_type, "interval")
        self.assertEqual(mock_instance.interval_seconds, 3600)
