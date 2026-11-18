# app/modules/email_sender.py
import smtplib
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app import logger


def send_backup_report_email(
    total: int,
    changed: list,
    failed: list,
    recipients: list[str],
    smtp_host: str = None,
    smtp_from: str = None,
    smtp_auth: bool = None,
    smtp_port: int = None,
    smtp_user: str = None,
    smtp_password: str = None,
    base_url: str = None,
    first_backups: list | None = None,
    unchanged: int | None = None,
    skipped: list | None = None,
):
    """
    Send only changes and errors. Legacy summary arguments remain accepted
    for compatibility but are not included in email notifications.
    """
    if not recipients:
        logger.info("No recipients, skipping email send")
        return

    changed = [
        device
        for device in changed
        if not device.get("skipped")
        and not device.get("first_backup")
        and device.get("is_enabled") is not False
    ]
    failed = [
        device
        for device in failed
        if not device.get("skipped") and device.get("is_enabled") is not False
    ]
    if not changed and not failed:
        logger.info("No configuration changes or errors, skipping email send")
        return

    msg = MIMEMultipart()
    msg["From"] = smtp_from
    msg["Subject"] = f"🔧 NABS: Backup Configuration Report"
    msg["To"] = recipients[0]
    if len(recipients) > 1:
        msg["Cc"] = ", ".join(recipients[1:])

    status = "Successfully" if not failed else "With errors"
    body = f"""
    <h2>Backup Configuration Report</h2>
    <p><strong>Status:</strong> {status}</p>
    <p><strong>Devices with changes:</strong> {len(changed)}</p>
    <p><strong>Errors:</strong> {len(failed)}</p>
    """

    if changed:
        body += "<h3>Devices with changes:</h3><ul>"
        for d in changed:
            device_link = ""
            if base_url and d.get("device_id"):
                device_link = f' - <a href="{escape(base_url)}/diff_page/{d["device_id"]}">🔍 View full diff in NABS</a>'
            hostname = escape(str(d.get("hostname") or d["ip"]))
            ip = escape(str(d["ip"]))
            model = escape(f'{d["vendor"]} {d["model"]}')
            body += f"<li><b>{hostname}</b> ({ip}) - {model}{device_link}"
            if d.get("diff_summary"):
                body += f'<pre style="background:#f4f4f4; padding:5px; margin-top:5px;">{escape(d["diff_summary"])}</pre>'
                if d.get("diff_truncated"):
                    body += "<p><small>... (truncated, see full diff via link above)</small></p>"
            body += "</li>"
        body += "</ul>"
    #
    if failed:
        body += "<h3>Errors:</h3><ul>"
        for f in failed:
            hostname = f.get("hostname", "Unknown")
            ip = f.get("ip", "")
            error = f.get("error", "Unknown error")
            body += f"<li><b>{escape(str(hostname))}</b> ({escape(str(ip))}): {escape(str(error))}</li>"
        body += "</ul>"

    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.set_debuglevel(0)
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()

            # Try without login
            try:
                server.send_message(msg, to_addrs=recipients)
                logger.info(
                    f"Email sent to {len(recipients)} recipients: {', '.join(recipients)}"
                )
                return
            except smtplib.SMTPSenderRefused:
                pass

            if smtp_user and smtp_password and smtp_auth:
                try:
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg, to_addrs=recipients)
                    logger.info(
                        f"Email sent with authentication to {len(recipients)} recipients"
                    )
                    return
                except Exception as auth_error:
                    logger.error(f"Authentication error: {auth_error}")
                    raise

            raise RuntimeError("Failed to send email: no valid authentication method")

    except Exception as e:
        logger.error(f"Error sending email: {e}")
