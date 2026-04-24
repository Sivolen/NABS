import os
import unittest
from unittest.mock import patch, MagicMock
from backuper import run_backup

os.environ["FLASK_ENV"] = "testing"


class TestRunBackup(unittest.TestCase):
    @patch("backuper.drivers.nornir_driver_sql")
    @patch("backuper.print_result")
    @patch("backuper.send_backup_report_email")
    @patch("backuper.get_notification_recipients")
    def test_run_backup_with_changes(
        self, mock_recipients, mock_send_email, mock_print, mock_nr_driver
    ):
        # Создаём суб-результат (аналог MultiResult[0])
        mock_sub_result = MagicMock()
        mock_sub_result.host = MagicMock(name="host1", hostname="10.0.0.1")
        mock_sub_result.result = {
            "changed": True,
            "ip": "10.0.0.1",
            "vendor": "Cisco",
            "model": "2960",
            "diff_summary": "diff line",
        }

        # Создаём сам task_result
        mock_task_result = MagicMock()
        mock_task_result.failed = False
        mock_task_result.__getitem__.return_value = mock_sub_result
        mock_task_result.__len__.return_value = 1  # чтобы len() работал

        mock_inventory = {"host1": mock_task_result}
        mock_nr = MagicMock()
        mock_nr.run.return_value = mock_inventory
        mock_nr_driver.return_value.__enter__.return_value = mock_nr

        mock_recipients.return_value = ["admin@example.com"]

        run_backup()

        mock_send_email.assert_called_once()
        kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(len(kwargs["changed"]), 1)
        self.assertEqual(len(kwargs["failed"]), 0)

    @patch("backuper.drivers.nornir_driver_sql")
    @patch("backuper.print_result")
    @patch("backuper.send_backup_report_email")
    @patch("backuper.get_notification_recipients")
    def test_run_backup_with_errors(
        self, mock_recipients, mock_send_email, mock_print, mock_nr_driver
    ):
        mock_sub_result = MagicMock()
        mock_sub_result.host = MagicMock(name="host1", hostname="10.0.0.1")
        mock_sub_result.result = None  # не используется при ошибке

        mock_task_result = MagicMock()
        mock_task_result.failed = True
        mock_task_result.exception = Exception("Connection error")
        mock_task_result.__getitem__.return_value = mock_sub_result
        mock_task_result.__len__.return_value = 1

        mock_inventory = {"host1": mock_task_result}
        mock_nr = MagicMock()
        mock_nr.run.return_value = mock_inventory
        mock_nr_driver.return_value.__enter__.return_value = mock_nr

        mock_recipients.return_value = ["admin@example.com"]

        run_backup()

        mock_send_email.assert_called_once()
        kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(len(kwargs["changed"]), 0)
        self.assertEqual(len(kwargs["failed"]), 1)
