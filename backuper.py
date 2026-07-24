#!venv/bin/python3
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from napalm.base.exceptions import (
    NapalmException,
    ConnectAuthError,
    ConnectTimeoutError,
    ConnectionClosedException,
)
from netmiko import NetmikoTimeoutException, NetmikoAuthenticationException
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
from nornir_netmiko.tasks import netmiko_send_command
from nornir.core.exceptions import (
    ConnectionException,
    ConnectionAlreadyOpen,
    ConnectionNotOpen,
    NornirExecutionError,
    NornirSubTaskError,
)
from nornir.core.task import Task, MultiResult, AggregatedResult
from paramiko.ssh_exception import SSHException

from app import logger
from app.modules.dbutils.db_drivers import get_driver_settings
from app.modules.dbutils.db_users import get_notification_recipients
from app.modules.email_sender import send_backup_report_email
from app.modules.helpers import Helpers
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    update_device_env,
    update_device_status,
)
from app.modules.dbutils.db_devices import (
    get_device_id,
    get_driver_switch_status,
    get_custom_driver_id,
    get_device_is_enabled,
)
from app.modules.log_parser import log_parser_for_task
from app.utils import (
    check_ip,
    clear_line_feed_on_device_config,
    clear_clock_period_on_device_config,
    clear_config_patterns,
    is_incomplete_config,
)
from app.modules.differ import diff_changed, get_diff_summary
from config import (
    fix_clock_period,
    conn_timeout,
    fix_double_line_feed,
    enable_clearing,
    clear_patterns,
    SMTP_HOST,
    SMTP_FROM,
    SMTP_PORT,
    SMTP_AUTH,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_DIFF_MAX_LINES,
    NABS_BASE_URL,
    NETMIKO_READ_TIMEOUT,
)

# Sanity-check settings (imported defensively so this keeps working even
# if config.py hasn't been updated yet with the new options).
try:
    from config import (
        enable_config_sanity_check,
        config_sanity_min_ratio,
        config_sanity_min_reference_lines,
        config_sanity_max_retries,
        config_sanity_retry_delay,
    )
except ImportError:
    enable_config_sanity_check = True
    config_sanity_min_ratio = 0.5
    config_sanity_min_reference_lines = 20
    config_sanity_max_retries = 2
    config_sanity_retry_delay = 5

from app import app
from app.modules.validation.runner import run_validation

drivers = Helpers(conn_timeout=conn_timeout)


# timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")


def custom_backup(
    task: Task, device_id: int, device_ip: str, timestamp: str
) -> dict | None:
    with app.app_context():
        try:
            custom_drivers_id = get_custom_driver_id(device_id=device_id)
            if not custom_drivers_id:
                logger.error(f"No custom driver found for device {device_id}")
                return None

            custom_drivers = get_driver_settings(
                custom_drivers_id=int(custom_drivers_id)
            )
            task.host.platform = custom_drivers["drivers_platform"]
            commands = custom_drivers["drivers_commands"].split(",")

            # Выполняем команды, сохраняя только результат последней
            config = ""
            for command in commands:
                # read_timeout = 30,  expect_string=r"."
                result = task.run(
                    netmiko_send_command,
                    command_string=command,
                    read_timeout=NETMIKO_READ_TIMEOUT,
                )
                config = result.result

            return {
                "vendor": custom_drivers["drivers_vendor"],
                "model": custom_drivers["drivers_model"],
                "config": str(config),
            }

        except (
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
        ) as connection_error:
            error_msg = log_parser_for_task(
                ipaddress=device_ip, hostname=task.host.name
            )
            if not error_msg:
                error_msg = str(connection_error)
            logger.error(
                f"Connection error on Device {device_id} ({device_ip}): {error_msg}"
            )
            update_ok = update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=error_msg,
            )
            if not update_ok:
                logger.critical(f"Failed to write error status for {device_ip} to DB")
            return {
                "connection_status": error_msg,
                "vendor": "Vendor not defined",
                "model": None,
                "last_changed": None,
                "config": None,
            }


def napalm_backup(
    task: Task, device_id: int, device_ip: str, timestamp: str
) -> dict | None:
    with app.app_context():
        try:
            device_result = task.run(task=napalm_get, getters=["get_facts", "config"])
            return {
                "vendor": device_result.result["get_facts"]["vendor"],
                "model": device_result.result["get_facts"]["model"],
                "config": device_result.result["config"]["running"],
            }
        except (
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
            NetmikoTimeoutException,
        ) as connection_error:
            error_msg = log_parser_for_task(
                ipaddress=device_ip, hostname=task.host.name
            )
            if not error_msg:
                error_msg = str(connection_error)
            logger.error(
                f"Connection error on Device {device_id} ({device_ip}): {error_msg}"
            )
            update_ok = update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=error_msg,
            )
            if not update_ok:
                logger.critical(f"Failed to write error status for {device_ip} to DB")
            return {
                "connection_status": error_msg,
                "vendor": "Vendor not defined",
                "model": None,
                "last_changed": None,
                "config": None,
            }


def backup_config_on_db(task: Task) -> dict | None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    with app.app_context():
        ipaddress: str = task.host.hostname
        if not check_ip(ipaddress):
            error_msg = f"Invalid IP address: {ipaddress}"
            logger.warning(f"Invalid IP address: {ipaddress}")
            return {"connection_status": error_msg}

        device_id = get_device_id(ipaddress=ipaddress)
        if not device_id:
            logger.error(f"Device not found in DB: {ipaddress}")
            return None
        device_id = int(device_id[0])

        if not get_device_is_enabled(device_id=device_id):
            logger.info(f"Device {ipaddress} is disabled, skipping backup")
            return None

        # Get the last known-good config for this device up front, so it can be used
        # both as the sanity-check reference and later for the real diff.
        last_config = get_last_config_for_device(device_id=device_id)
        last_config_content = last_config["last_config"] if last_config else None

        device_result = None
        candidate_config = None
        attempt = 0
        max_attempts = 1 + max(0, config_sanity_max_retries)

        while attempt < max_attempts:
            attempt += 1
            if get_driver_switch_status(device_id=device_id):
                device_result = custom_backup(
                    task=task,
                    device_id=device_id,
                    device_ip=ipaddress,
                    timestamp=timestamp,
                )
            else:
                device_result = napalm_backup(
                    task=task,
                    device_id=device_id,
                    device_ip=ipaddress,
                    timestamp=timestamp,
                )
            if not device_result:
                return {"connection_status": "Backup function returned no result"}

            candidate_config = device_result["config"]
            if not candidate_config:
                logger.warning(f"Empty configuration received for {ipaddress}")
                return {"connection_status": device_result.get("connection_status")}

            if enable_clearing:
                candidate_config = clear_config_patterns(
                    config=candidate_config, patterns=clear_patterns
                )

            if task.host.platform == "ios" and fix_clock_period:
                candidate_config = clear_clock_period_on_device_config(candidate_config)

            if fix_double_line_feed:
                candidate_config = clear_line_feed_on_device_config(candidate_config)

            if len(candidate_config.splitlines()) == 0:
                logger.warning(f"Empty configuration after cleaning for {ipaddress}")
                return {"connection_status": "Configuration empty after cleaning"}

            if not enable_config_sanity_check or not is_incomplete_config(
                candidate_config,
                last_config_content,
                min_ratio=config_sanity_min_ratio,
                min_reference_lines=config_sanity_min_reference_lines,
            ):
                break

            logger.warning(
                f"Suspiciously short/truncated config received from {ipaddress} "
                f"(attempt {attempt}/{max_attempts}) - likely a device CLI glitch, "
                f"not a real change."
            )
            if attempt < max_attempts:
                time.sleep(config_sanity_retry_delay)

        if enable_config_sanity_check and is_incomplete_config(
            candidate_config,
            last_config_content,
            min_ratio=config_sanity_min_ratio,
            min_reference_lines=config_sanity_min_reference_lines,
        ):
            error_msg = (
                f"Config for {ipaddress} still looks truncated after {max_attempts} "
                f"attempt(s); skipping save to avoid polluting history with a device glitch."
            )
            logger.error(error_msg)
            update_device_status(
                device_id=device_id, timestamp=timestamp, connection_status=error_msg
            )
            return {
                "ip": ipaddress,
                "hostname": task.host.name,
                "device_id": device_id,
                "connection_status": error_msg,
                "changed": False,
            }

        device_info = {
            "device_id": device_id,
            "vendor": device_result["vendor"],
            "model": device_result["model"],
            "timestamp": timestamp,
            "connection_status": "Ok",
        }
        update_device_env(**device_info)

        # Run validation after every successful config fetch, whether or not
        # the config changed since the last backup, and even on the very
        # first backup for this device - validation checks the CURRENT state
        # of the device, not the diff.
        try:
            run_validation(
                device_id=device_id, config=candidate_config, timestamp=timestamp
            )
        except Exception as e:
            logger.warning(f"Validation run failed for device {device_id}: {e}")

        if not last_config:
            write_config(
                ipaddress=ipaddress, config=candidate_config, timestamp=timestamp
            )
            return None

        changed = not diff_changed(
            config1=candidate_config, config2=last_config_content
        )
        diff_summary = None
        diff_truncated = False
        if changed:
            diff_summary, diff_truncated = get_diff_summary(
                last_config_content, candidate_config, max_lines=EMAIL_DIFF_MAX_LINES
            )
            write_config(
                ipaddress=ipaddress, config=candidate_config, timestamp=timestamp
            )

        return {
            "ip": ipaddress,
            "hostname": task.host.name,
            "device_id": device_id,
            "vendor": device_result["vendor"],
            "model": device_result["model"],
            "changed": changed,
            "timestamp": timestamp,
            "diff_summary": diff_summary,
            "diff_truncated": diff_truncated,
        }


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
            "hostname": host.name if host else hostname,
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
            "hostname": host.name if host else hostname,
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
                if device_data and device_data.get("changed"):
                    changed_devices.append(device_data)

            # Outputting results to the console (for debugging)
            print_result(result, vars=["stdout"])  # type: ignore

            # Sending an email report
            with app.app_context():
                recipient_emails: List[str] = get_notification_recipients()

            if recipient_emails and (changed_devices or failed_devices):
                send_backup_report_email(
                    total=total_devices,
                    changed=changed_devices,
                    failed=failed_devices,
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
                elif not changed_devices and not failed_devices:
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
