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
        for extra in (
            {},
            {"first_backups": [{"hostname": "first-only"}]},
            {"skipped": [{"hostname": "disabled-only"}], "unchanged": 10},
        ):
            with self.subTest(extra=extra), patch("smtplib.SMTP") as smtp:
                send_backup_report_email(
                    total=10,
                    changed=[],
                    failed=[],
                    recipients=["test@example.com"],
                    **extra
                )
                smtp.assert_not_called()

    def test_mixed_report_contains_only_changes_and_errors(self):
        with patch("smtplib.SMTP") as smtp:
            send_backup_report_email(
                total=100,
                changed=[
                    {
                        "hostname": "changed-switch",
                        "ip": "192.0.2.1",
                        "vendor": "Cisco",
                        "model": "Lab",
                    },
                    {"hostname": "disabled-change", "is_enabled": False},
                ],
                failed=[
                    {
                        "hostname": "failed-switch",
                        "ip": "192.0.2.2",
                        "error": "SSH failed",
                    },
                    {"hostname": "disabled-error", "skipped": True},
                ],
                first_backups=[{"hostname": "first-switch"}],
                skipped=[{"hostname": "disabled-switch", "reason": "Device disabled"}],
                unchanged=90,
                recipients=["test@example.com"],
                smtp_from="nabs@example.com",
                smtp_host="localhost",
                smtp_port=25,
            )
            server = smtp.return_value.__enter__.return_value
            server.send_message.assert_called_once()
            message = server.send_message.call_args.args[0]
            html = next(
                part.get_payload(decode=True).decode("utf-8")
                for part in message.walk()
                if part.get_content_type() == "text/html"
            )
            self.assertIn("changed-switch", html)
            self.assertIn("failed-switch", html)
            self.assertIn("SSH failed", html)
            for hidden in (
                "disabled-change",
                "disabled-error",
                "first-switch",
                "disabled-switch",
                "Skipped",
                "Unchanged",
                "First backups",
                "Devices processed",
            ):
                self.assertNotIn(hidden, html)

    def test_disabled_results_never_trigger_smtp(self):
        with patch("smtplib.SMTP") as smtp:
            send_backup_report_email(
                total=2,
                changed=[{"hostname": "disabled", "is_enabled": False}],
                failed=[{"hostname": "skipped", "skipped": True}],
                recipients=["test@example.com"],
            )
            smtp.assert_not_called()
