"""Poll one device through Nornir and save its configuration."""

import time
from datetime import datetime

from netmiko import NetmikoTimeoutException
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command
from nornir.core.exceptions import (
    ConnectionException,
    ConnectionAlreadyOpen,
    ConnectionNotOpen,
    NornirExecutionError,
    NornirSubTaskError,
)
from nornir.core.task import Task

from app import app, db, logger
from app.models import Devices
from app.modules.backup_lock import device_backup_lock
from app.modules.dbutils.db_drivers import get_driver_settings
from app.modules.dbutils.db_devices import (
    get_device_id,
    get_driver_switch_status,
    get_custom_driver_id,
    get_device_is_enabled,
)
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    update_device_env,
    update_device_status,
)
from app.modules.differ import diff_changed, get_diff_summary
from app.modules.helpers import Helpers
from app.modules.validators import driver_commands
from app.modules.validation.runner import run_validation
from app.utils import (
    check_ip,
    clear_line_feed_on_device_config,
    clear_clock_period_on_device_config,
    clear_config_patterns,
    is_incomplete_config,
)
import config as settings
from config import (
    conn_timeout,
    fix_clock_period,
    fix_double_line_feed,
    enable_clearing,
    clear_patterns,
    EMAIL_DIFF_MAX_LINES,
    NETMIKO_READ_TIMEOUT,
)

enable_config_sanity_check = getattr(settings, "enable_config_sanity_check", True)
config_sanity_min_ratio = getattr(settings, "config_sanity_min_ratio", 0.5)
config_sanity_min_reference_lines = getattr(
    settings, "config_sanity_min_reference_lines", 20
)
config_sanity_max_retries = getattr(settings, "config_sanity_max_retries", 2)
config_sanity_retry_delay = getattr(settings, "config_sanity_retry_delay", 5)


def backup_device(device_id):
    """Run the same Nornir task as bulk backups for one database device."""
    with app.app_context():
        device = db.session.get(Devices, device_id)
        if device is None:
            return {
                "skipped": True,
                "connection_status": "Device removed from inventory",
            }
        if not device.is_enabled:
            return {"skipped": True, "connection_status": "Device disabled"}
        ipaddress = device.device_ip
        _release_db_connection()
        with Helpers(
            ipaddress=ipaddress, conn_timeout=conn_timeout
        ).nornir_driver_sql() as inventory:
            # Check both ID and address: an address can be reassigned while inventory loads.
            inventory = inventory.filter(name=str(device_id))
            result = inventory.run(
                task=backup_config_on_db, name="Backup configuration"
            )
            host_result = result.get(str(device_id))
            if not host_result:
                return {
                    "skipped": True,
                    "connection_status": "Device changed or removed",
                }
            value = host_result[0].result
            if isinstance(value, dict):
                return value
            raise RuntimeError("Backup task returned no result")


def run_backup_config_on_db(data):
    """Compatibility entry point for the existing synchronous HTTP endpoint."""
    with app.app_context():
        row = get_device_id(ipaddress=data.get("device"))
        if not row:
            return {
                "skipped": True,
                "connection_status": "Device removed from inventory",
            }
        return backup_device(int(row[0]))


def _release_db_connection() -> None:
    """
    Give the PostgreSQL connection back to the pool BEFORE a long network operation.

    A task runs inside `with app.app_context()`, and the session of that context keeps
    the connection it got for its first query ("idle in transaction") until the context
    ends. With 20 Nornir threads that held up to 20 (+ nested contexts) connections for
    the whole SSH session - minutes - and forced a huge pool. Only reads happened before
    this call (the getters return dicts / plain values), so a rollback loses nothing; the
    next query takes a connection again.
    """
    try:
        db.session.rollback()
    except Exception as release_error:  # never let this break a backup
        logger.warning(f"Could not release the DB connection: {release_error}")


def _current_backup_error(stage, error):
    if isinstance(error, NornirSubTaskError):
        error = getattr(error.result, "exception", None) or error
    lines = str(error).strip().splitlines()
    detail = f": {lines[0]}" if lines else ""
    return f"{stage} ({type(error).__name__}){detail}"[:300]


def custom_backup(
    task: Task, device_id: int, device_ip: str, timestamp: str
) -> dict | None:
    with app.app_context():
        stage = "Connect with Netmiko"
        try:
            custom_drivers_id = get_custom_driver_id(device_id=device_id)
            if not custom_drivers_id:
                logger.error(f"No custom driver found for device {device_id}")
                return None

            custom_drivers = get_driver_settings(
                custom_drivers_id=int(custom_drivers_id)
            )
            task.host.platform = custom_drivers["drivers_platform"]
            commands = driver_commands(custom_drivers["drivers_commands"])
            _release_db_connection()  # the commands below can take minutes

            # Выполняем команды, сохраняя только результат последней
            config = ""
            for index, command in enumerate(commands, start=1):
                stage = (
                    "Read config with Netmiko"
                    if index == len(commands)
                    else f"Prepare device (command {index})"
                )
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
            error_msg = _current_backup_error(stage, connection_error)
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
            error_msg = _current_backup_error(
                "Read config with NAPALM", connection_error
            )
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
            return {
                "skipped": True,
                "connection_status": "Device removed from inventory",
            }
        device_id = int(device_id[0])

        with device_backup_lock(device_id) as acquired:
            if not acquired:
                return {"skipped": True, "connection_status": "Backup already running"}
            try:
                return _backup_device(task, ipaddress, device_id, timestamp)
            except Exception as error:
                db.session.rollback()
                message = _current_backup_error("Backup processing", error)
                logger.exception("Backup failed for device %s", device_id)
                update_device_status(
                    device_id=device_id, timestamp=timestamp, connection_status=message
                )
                return {"device_id": device_id, "connection_status": message}


def _backup_device(task, ipaddress, device_id, timestamp):
    if not get_device_is_enabled(device_id=device_id):
        logger.info(f"Device {ipaddress} is disabled, skipping backup")
        return {"skipped": True, "connection_status": "Device disabled"}

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
        use_custom_driver = get_driver_switch_status(device_id=device_id)
        _release_db_connection()  # the SSH session below can take minutes
        if use_custom_driver:
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
            message = device_result.get("connection_status")
            if not message or message == "Ok":
                message = "Empty configuration"
            update_device_status(
                device_id=device_id, timestamp=timestamp, connection_status=message
            )
            return {"connection_status": message}

        if enable_clearing:
            candidate_config = clear_config_patterns(
                config=candidate_config, patterns=clear_patterns
            )

        if task.host.platform == "ios" and fix_clock_period:
            candidate_config = clear_clock_period_on_device_config(candidate_config)

        if fix_double_line_feed:
            candidate_config = clear_line_feed_on_device_config(candidate_config)

        if not candidate_config.strip():
            message = "Configuration empty after cleaning"
            update_device_status(
                device_id=device_id, timestamp=timestamp, connection_status=message
            )
            return {"connection_status": message}

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
            "hostname": task.host.data.get("display_name") or task.host.name,
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
    changed = not last_config or not diff_changed(candidate_config, last_config_content)
    if changed and not write_config(
        ipaddress=ipaddress, config=candidate_config, timestamp=timestamp
    ):
        message = "Could not save configuration"
        update_device_status(
            device_id=device_id, timestamp=timestamp, connection_status=message
        )
        return {"connection_status": message}
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

    first_backup = last_config is None
    diff_summary = None
    diff_truncated = False
    if changed and not first_backup:
        diff_summary, diff_truncated = get_diff_summary(
            last_config_content, candidate_config, max_lines=EMAIL_DIFF_MAX_LINES
        )

    return {
        "connection_status": "Ok",
        "ip": ipaddress,
        "hostname": task.host.data.get("display_name") or task.host.name,
        "device_id": device_id,
        "vendor": device_result["vendor"],
        "model": device_result["model"],
        "first_backup": first_backup,
        "changed": changed and not first_backup,
        "timestamp": timestamp,
        "last_changed": timestamp if changed else (last_config or {}).get("timestamp"),
        "diff_summary": diff_summary,
        "diff_truncated": diff_truncated,
    }
