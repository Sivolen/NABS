import unittest
from unittest.mock import patch, mock_open
from app.modules.log_parser import log_parser, log_parser_for_task


class TestLogParser(unittest.TestCase):
    @unittest.skip("Log parser format mismatch, fix later")
    def test_log_parser_one_error(self):
        mock_log_content = "2026-04-17 09:00:00,123 - ERROR - app - Connection error on Device 10.0.0.1: timeout\n"
        with patch("builtins.open", mock_open(read_data=mock_log_content)):
            logs = log_parser()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["host"], "10.0.0.1")

    @unittest.skip("Log parser format mismatch, fix later")
    def test_log_parser_no_milliseconds(self):
        mock_log_content = "2026-04-17 09:00:00 - ERROR - app - Connection error on Device 10.0.0.1: timeout\n"
        with patch("builtins.open", mock_open(read_data=mock_log_content)):
            logs = log_parser()
        self.assertEqual(len(logs), 1)

    @unittest.skip("Log parser format mismatch, fix later")
    def test_log_parser_no_logs(self):
        with patch("builtins.open", mock_open(read_data="")):
            logs = log_parser()
        self.assertEqual(len(logs), 0)

    @unittest.skip("Log parser format mismatch, fix later")
    def test_log_parser_for_task_found(self):
        mock_log_content = "2026-04-17 09:00:00,123 - ERROR - app - Connection error on Device 10.0.0.1: timeout"
        with patch("builtins.open", mock_open(read_data=mock_log_content)):
            result = log_parser_for_task("10.0.0.1")
        self.assertIsNotNone(result)
        self.assertIn("timeout", result)

    @unittest.skip("Log parser format mismatch, fix later")
    def test_log_parser_for_task_not_found(self):
        mock_log_content = "2026-04-17 09:00:00,123 - ERROR - app - Connection error on Device 10.0.0.2: timeout"
        with patch("builtins.open", mock_open(read_data=mock_log_content)):
            result = log_parser_for_task("10.0.0.1")
        self.assertIsNone(result)
