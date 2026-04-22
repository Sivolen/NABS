import os
import unittest
from unittest.mock import patch
from email.mime.multipart import MIMEMultipart
import base64
from app.modules.email_sender import send_backup_report_email

os.environ["FLASK_ENV"] = "testing"


def decode_base64_content(encoded_str):
    """Декодирует base64 строку в UTF-8."""
    return base64.b64decode(encoded_str).decode("utf-8")


class TestEmail(unittest.TestCase):
    def test_email_body_contains_changes(self):
        changed_devices = [
            {
                "ip": "10.0.0.1",
                "vendor": "Cisco",
                "model": "2960",
                "device_id": 123,
                "diff_summary": "diff line",
                "diff_truncated": False,
            }
        ]
        failed_devices = []
        recipients = ["test@example.com"]

        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = mock_smtp.return_value.__enter__.return_value
            send_backup_report_email(
                total=1,
                changed=changed_devices,
                failed=failed_devices,
                recipients=recipients,
                smtp_host="localhost",
                smtp_from="nabs@example.com",
                smtp_port=25,
                base_url="https://nabs.example.com",
            )
            mock_server.send_message.assert_called_once()
            args, _ = mock_server.send_message.call_args
            msg = args[0]
            self.assertIsInstance(msg, MIMEMultipart)

            # Извлекаем HTML-часть и декодируем
            html_content = None
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload()
                    # Если закодировано в base64
                    if part.get("Content-Transfer-Encoding") == "base64":
                        html_content = base64.b64decode(payload).decode("utf-8")
                    else:
                        html_content = payload
                    break
            self.assertIsNotNone(html_content)
            self.assertIn("Devices with changes", html_content)
            self.assertIn("10.0.0.1", html_content)
            self.assertIn("/diff_page/123", html_content)

    def test_email_no_changes_no_errors(self):
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = mock_smtp.return_value.__enter__.return_value
            send_backup_report_email(
                total=0,
                changed=[],
                failed=[],
                recipients=["test@example.com"],
                smtp_host="localhost",
                smtp_from="nabs@example.com",
                smtp_port=25,
            )
            mock_server.send_message.assert_called_once()
            args, _ = mock_server.send_message.call_args
            msg = args[0]
            html_content = None
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload()
                    if part.get("Content-Transfer-Encoding") == "base64":
                        html_content = base64.b64decode(payload).decode("utf-8")
                    else:
                        html_content = payload
                    break
            # Проверяем, что в HTML есть указание на 0 изменений
            self.assertIn("<strong>Devices with changes:</strong> 0", html_content)
