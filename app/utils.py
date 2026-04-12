import re
import psutil
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app import logger


# Checking ipaddresses
def check_ip(ipaddress: int or str) -> bool:
    """
    Check ip address
    """
    pattern = (
        r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1"
        "[0-9]"
        "{2}|2[0-4]["
        "0-9"
        "]|25[0-5])$"
    )
    return True if re.findall(pattern, ipaddress) else False


# The function needed for delete blank line on device config
def clear_line_feed_on_device_config(config: str) -> str:
    """
    The function needed for replace double line feed on device config
    """
    # Pattern for replace
    # pattern = r"^\n"
    # pattern = r"\n\s*\n"
    # pattern = r"^\n\n"
    # pattern = r"^\s*$"
    # pattern = r"\n\n"
    pattern = r"(\n){2,}"
    if re.match(r"^\n", config):
        # Remove first line
        config = re.sub(r"^\n", "", config)
    # Return changed config with delete free space
    return re.sub(pattern, "\n", str(config))


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_clock_period_on_device_config(config: str) -> str:
    """
    The function needed replace ntp clock period on cisco switch, but he's always changing
    """
    # pattern for replace
    pattern = r"ntp\sclock-period\s[0-9]{1,30}\n"
    # Returning changed config or if this command not found return original file
    return re.sub(pattern, "", str(config))


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_config_patterns(config: str, patterns: list) -> str:
    """
    Clears the given patterns from the config string.
    """
    for pattern in patterns:
        config = re.sub(pattern, "", str(config))
    return config


def get_server_params() -> dict:
    """
    This function gets the server parameters
    """
    memory = psutil.virtual_memory()  # Общая информация о памяти
    disk_usage = psutil.disk_usage("/")  # Информация о диске, на котором установлена ОС

    return {
        "cpu_percent": psutil.cpu_percent(),
        "cpu_freq": psutil.cpu_freq(),
        "cpu_count": psutil.cpu_count(),
        "memory_total": int(memory.total / 1024 / 1024),
        "memory_used": int(memory.used / 1024 / 1024),
        "memory_free": int(memory.free / 1024 / 1024),
        "disk_total": int(disk_usage.total / 1024 / 1024 / 1024),
        "disk_used": int(disk_usage.used / 1024 / 1024 / 1024),
        "disk_free": int(disk_usage.free / 1024 / 1024 / 1024),
    }


def send_backup_report_email(
    total: int,
    changed: list,
    failed: list,
    recipients: list[str],
    success: bool = True,
    error: str = None,
    smtp_host: str = None,
    smtp_from: str = None,
    smtp_auth: bool = None,
    smtp_port: int = None,
    smtp_user: str = None,
    smtp_password: str = None,
):
    msg = MIMEMultipart()
    msg["From"] = smtp_from
    msg["Subject"] = f"🔧 NABS: {'✅' if success else '❌'} Backup Configuration Report"

    msg["To"] = recipients[0]
    if len(recipients) > 1:
        msg["Cc"] = ", ".join(recipients[1:])

    status = "Successfully" if success else "With errors"
    body = f"""
    <h2>Backup Configuration Report</h2>
    <p><strong>Status:</strong> {status}</p>
    <p><strong>Devices processed:</strong> {total}</p>
    <p><strong>Devices with changes:</strong> {len(changed)}</p>
    <p><strong>Errors:</strong> {len(failed)}</p>
    """

    if error:
        body += f"<p><strong>Errors:</strong> {error}</p>"

    if changed:
        body += "<h3>Devices with changes:</h3><ul>"
        for d in changed:
            body += f'<li><b>{d["ip"]}</b> ({d["vendor"]} {d["model"]})'
            if d.get("diff_summary"):
                body += f'<pre style="background:#f4f4f4; padding:5px; margin-top:5px;">{d["diff_summary"]}</pre>'
            body += '</li>'
        body += "</ul>"

    if failed:
        body += "<h3>Errors:</h3><ul>"
        body += "".join(
            [f'<li><b>{f["hostname"]}</b>: {f["error"]}</li>' for f in failed]
        )
        body += "</ul>"

    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.set_debuglevel(0)
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()

            # Попробовать без логина
            try:
                server.send_message(msg, to_addrs=recipients)
                logger.info(
                    f"📧 The report has been sent {len(recipients)} to the recipients: {', '.join(recipients)}"
                )
                return
            except smtplib.SMTPSenderRefused:
                pass

            if smtp_user and smtp_password and smtp_auth:
                try:
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg, to_addrs=recipients)
                    logger.info(
                        f"📧 Report sent with authentication {len(recipients)} to the recipients"
                    )
                    return
                except Exception as auth_error:
                    logger.error(
                        f"❌ Authentication error when sending email: {auth_error}"
                    )
                    raise

            raise RuntimeError("Failed to send email: none of the methods worked")

    except Exception as e:
        logger.error(f"❌ Error sending email: {e}")
