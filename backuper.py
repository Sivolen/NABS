#!venv/bin/python3
"""Bulk backup entry point used by the CLI, scheduler and manual batch action."""

from typing import List, Dict, Any, Optional, Tuple

from nornir.core.exceptions import NornirExecutionError
from nornir.core.task import MultiResult, AggregatedResult
from nornir_utils.plugins.functions import print_result

from app import app, logger
from app.modules.backup_service import backup_config_on_db
from app.modules.dbutils.db_users import get_notification_recipients
from app.modules.email_sender import send_backup_report_email
from app.modules.helpers import Helpers
from config import (
    conn_timeout,
    SMTP_HOST,
    SMTP_FROM,
    SMTP_PORT,
    SMTP_AUTH,
    SMTP_USER,
    SMTP_PASSWORD,
    NABS_BASE_URL,
)

drivers = Helpers(conn_timeout=conn_timeout)


def _get_device_error(
    hostname: str,
    task_result: MultiResult,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Checks the task's result for errors.
    Returns (has_error, error_info_dict) or (False, None) if there is no error.
    """
    host = task_result[0].host if task_result and len(task_result) > 0 else None
    device_data = (
        task_result[0].result if task_result and len(task_result) > 0 else None
    )

    if device_data and device_data.get("skipped"):
        return False, None

    # Case 1: Task failed (exception)
    if task_result.failed:
        error_msg = (
            device_data.get("connection_status")
            if device_data
            and device_data.get("connection_status")
            and device_data["connection_status"] != "Ok"
            else str(task_result.exception)
            if task_result.exception
            else "Unknown error"
        )
        return True, {
            "hostname": (host.data.get("display_name") or host.name)
            if host
            else hostname,
            "ip": host.hostname if host else None,
            "error": error_msg,
        }

    # Case 2: The task succeeded but returned a dictionary with an error
    if (
        device_data
        and device_data.get("connection_status")
        and device_data["connection_status"] != "Ok"
    ):
        return True, {
            "hostname": (host.data.get("display_name") or host.name)
            if host
            else hostname,
            "ip": host.hostname if host else None,
            "error": device_data["connection_status"],
        }

    # There is no error
    return False, None


def run_backup() -> None:
    """The main backup process: polling devices, collecting changes and errors, and sending a report."""
    try:
        with drivers.nornir_driver_sql() as nr_driver:
            # Run backup on all devices
            result: AggregatedResult = nr_driver.run(
                name="Backup configurations",
                task=backup_config_on_db,
            )

            changed_devices: List[Dict[str, Any]] = []
            failed_devices: List[Dict[str, Any]] = []
            first_backups: List[Dict[str, Any]] = []
            skipped_devices: List[Dict[str, Any]] = []
            unchanged_devices = 0
            total_devices: int = 0

            # Analysis of the results of each device
            for hostname, task_result in result.items():
                total_devices += 1

                # Checking if there is an error in the task
                has_error, error_info = _get_device_error(hostname, task_result)
                if has_error:
                    failed_devices.append(error_info)
                    continue

                # If there is no error, we check whether the configuration has changed
                device_data = (
                    task_result[0].result
                    if task_result and len(task_result) > 0
                    else None
                )
                if not device_data or device_data.get("skipped"):
                    host = task_result[0].host
                    skipped_devices.append(
                        {
                            "hostname": (host.data.get("display_name") or host.name)
                            if host
                            else hostname,
                            "ip": host.hostname if host else "",
                            "reason": (device_data or {}).get(
                                "connection_status", "No backup attempted"
                            ),
                        }
                    )
                elif device_data.get("first_backup"):
                    first_backups.append(device_data)
                elif device_data.get("changed"):
                    changed_devices.append(device_data)
                else:
                    unchanged_devices += 1

            logger.info(
                "Backup totals: %s devices, %s first backups, %s changed, %s unchanged, %s skipped, %s failed",
                total_devices,
                len(first_backups),
                len(changed_devices),
                unchanged_devices,
                len(skipped_devices),
                len(failed_devices),
            )

            # Outputting results to the console (for debugging)
            print_result(result, vars=["stdout"])  # type: ignore

            # Sending an email report
            with app.app_context():
                recipient_emails: List[str] = get_notification_recipients()

            if recipient_emails and (
                first_backups or changed_devices or failed_devices
            ):
                send_backup_report_email(
                    total=total_devices,
                    changed=changed_devices,
                    failed=failed_devices,
                    first_backups=first_backups,
                    unchanged=unchanged_devices,
                    skipped=skipped_devices,
                    recipients=recipient_emails,
                    smtp_host=SMTP_HOST,
                    smtp_from=SMTP_FROM,
                    smtp_port=SMTP_PORT,
                    smtp_auth=SMTP_AUTH,
                    smtp_user=SMTP_USER,
                    smtp_password=SMTP_PASSWORD,
                    base_url=NABS_BASE_URL,
                )
            else:
                if not recipient_emails:
                    logger.info(
                        "No users have subscribed to notifications. Email not sent."
                    )
                elif not first_backups and not changed_devices and not failed_devices:
                    logger.info("No changes or errors. The email is not sent.")

    except NornirExecutionError as e:
        logger.error(f"Backup process failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


def main() -> None:
    logger.info("Starting backup process")
    run_backup()
    logger.info("Backup process completed")


if __name__ == "__main__":
    main()
