import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from netmiko import (
    ConnectHandler,
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)
from napalm import get_network_driver
from napalm.base.exceptions import (
    NapalmException,
    ConnectionException,
    ConnectAuthError,
    ConnectTimeoutError,
    ConnectionClosedException,
)

from app.modules.dbutils.db_drivers import get_driver_settings
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    update_device_env,
    update_device_status,
    get_user_and_pass,
)
from app.modules.dbutils.db_devices import (
    get_device_id,
    get_custom_driver_id,
    get_driver_switch_status,
    get_device_is_enabled,
)

from app import logger, app
from app.modules.log_parser import log_parser_for_task

from app.utils import (
    check_ip,
    clear_clock_period_on_device_config,
    clear_line_feed_on_device_config,
    clear_config_patterns,
    is_incomplete_config,
)
from config import (
    conn_timeout,
    fix_clock_period,
    fix_double_line_feed,
    clear_patterns,
    enable_clearing,
    NETMIKO_READ_TIMEOUT,
    # fix_platform_list,
)

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
from app.modules.differ import diff_changed
from app.modules.crypto import decrypt
from config import TOKEN

# now = datetime.now()
# # Formatting date time
# timestamp = now.strftime("%Y-%m-%d %H:%M")


def backup_runner(napalm_driver: str, ipaddress: str) -> None:
    executor = ThreadPoolExecutor(max_workers=5)
    executor.submit(backup_config_on_db, napalm_driver, ipaddress)


def run_backup_config_on_db(previous_config_data):
    ipaddress = previous_config_data["device"]
    driver = previous_config_data["driver"]
    result = backup_config_on_db(ipaddress=ipaddress, napalm_driver=driver)
    return result


def custom_buckup(ipaddress: str, device_id: int, timestamp: str) -> dict | None:
    with app.app_context():
        # Getting driver settings and authentication data
        custom_drivers_id = get_custom_driver_id(device_id=device_id)
        custom_drivers = get_driver_settings(custom_drivers_id=int(custom_drivers_id))
        auth_data = get_user_and_pass(device_id=device_id)

        # Forming connection parameters
        task = {
            "device_type": custom_drivers["drivers_platform"],
            "host": ipaddress,
            "username": auth_data["credentials_username"],
            "password": decrypt(auth_data["credentials_password"], key=TOKEN),
            "port": auth_data["ssh_port"],
            "conn_timeout": conn_timeout,
        }

        try:
            # Подключение к устройству
            with ConnectHandler(**task) as ssh:
                commands = custom_drivers["drivers_commands"].split(",")
                config = None

                for i, command in enumerate(commands):
                    command = command.strip()
                    if not command:
                        logger.warning(
                            f"Empty command found for Device {device_id} ({ipaddress}). Skipping."
                        )
                        continue

                    try:
                        # Sending a command
                        current_config = ssh.send_command(
                            command_string=command, read_timeout=NETMIKO_READ_TIMEOUT
                        )

                        # We save the output of only the last command
                        if i == len(commands) - 1:
                            config = current_config

                    except OSError as os_error:
                        # Handling the error "Search pattern never detected"
                        logger.error(
                            f"Error on Device {device_id} ({ipaddress}): Incorrect driver configuration. "
                            f"Command '{command}' failed with error: {os_error}"
                        )
                        update_device_status(
                            device_id=device_id,
                            timestamp=timestamp,
                            connection_status=f"Driver error: Command '{command}' failed with error: {os_error}",
                        )
                        return {
                            "connection_status": f"Driver error: Command '{command}' failed with error: {os_error}",
                            "vendor": custom_drivers["drivers_vendor"],
                            "model": custom_drivers["drivers_model"],
                            "last_changed": None,
                            "config": None,
                            "message": "Incorrect driver configuration. Please check the commands and prompts.",
                            "details": str(os_error),
                        }

        except (
            NetmikoTimeoutException,
            NetmikoAuthenticationException,
        ) as connection_error:
            logger.info(
                f"An error occurred on Device {device_id} ({ipaddress}): {connection_error}"
            )
            # Checking the device status in the database
            check_status = log_parser_for_task(ipaddress=ipaddress)
            update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=check_status
                if check_status is not None
                else "Connection error",
            )
            return {
                "connection_status": str(connection_error),
                "vendor": "Vendor not defined",
                "model": None,
                "last_changed": None,
                "config": None,
            }

        return {
            "connection_status": "Ok",
            "vendor": custom_drivers["drivers_vendor"],
            "model": custom_drivers["drivers_model"],
            "last_changed": None,  # If needed, add logic to get last_changed
            "config": config,
        }


def napalm_backup(ipaddress: str, device_id: int, napalm_driver: str, timestamp: str):
    auth_data = get_user_and_pass(device_id=device_id)
    try:
        connect_driver = get_network_driver(napalm_driver)
        # device_id = get_device_id(ipaddress=ipaddress)[0]
        napalm_device = connect_driver(
            hostname=ipaddress,
            username=auth_data["credentials_username"],
            password=decrypt(auth_data["credentials_password"], key=TOKEN),
            optional_args={
                "port": auth_data["ssh_port"],
                "conn_timeout": conn_timeout,
                "fast_cli": False,
            },
        )
        napalm_device.open()
        device_result = napalm_device.get_facts()
        device_config = napalm_device.get_config()
        candidate_config = device_config["running"]
    except (
        NapalmException,
        ConnectionException,
        ConnectAuthError,
        ConnectTimeoutError,
        ConnectionClosedException,
    ) as connection_error:
        device_info = {
            "connection_status": connection_error,
            "vendor": "Vendor not defined",
            "model": None,
            "last_changed": None,
            "config": None,
        }
        update_device_status(
            device_id=device_id,
            timestamp=timestamp,
            connection_status=str(connection_error),
        )
        return device_info
    return {
        "connection_status": "Ok",
        "vendor": device_result["vendor"],
        "model": device_result["model"],
        "config": candidate_config,
    }


def backup_config_on_db(napalm_driver: str, ipaddress: str) -> dict | None:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    now = datetime.now()
    # Formatting date time
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    #
    if not check_ip(ipaddress):
        return logger.info(f"Ipaddress: {ipaddress} is invalid")
    #
    device_id = get_device_id(ipaddress=ipaddress)
    if not device_id:
        return logger.info(f"Device id: {ipaddress} is invalid")
    device_id = int(device_id[0])
    # check if device is enabled
    if not get_device_is_enabled(device_id=device_id):
        return logger.info(f"Device id: {ipaddress} is disabled")
    # Get the latest configuration file from the database up front - it's used both
    # as the sanity-check reference and later for the real diff.
    last_config = get_last_config_for_device(device_id=device_id)
    last_config_content = last_config["last_config"] if last_config else None

    # Run the task to get the configuration from the device, retrying a couple of
    # times if the result looks like a truncated/glitched CLI read (e.g. some
    # Eltex MES / Cisco SG350 switches occasionally echo back just the prompt
    # instead of the full config when the CLI is slow/overloaded).
    device_result = None
    candidate_config = None
    attempt = 0
    max_attempts = 1 + max(0, config_sanity_max_retries)

    while attempt < max_attempts:
        attempt += 1
        if get_driver_switch_status(device_id=device_id):
            device_result = custom_buckup(
                ipaddress=ipaddress, device_id=device_id, timestamp=timestamp
            )
        else:
            device_result = napalm_backup(
                ipaddress=ipaddress,
                device_id=device_id,
                napalm_driver=napalm_driver,
                timestamp=timestamp,
            )

        if device_result["config"] is None:
            device_info: dict = {
                "device_id": device_id,
                "vendor": device_result["vendor"],
                "model": device_result["model"],
                "timestamp": str(timestamp),
                "connection_status": device_result["connection_status"],
                "device_ip": str(ipaddress),
                "last_changed": None,
            }
            return device_info

        candidate_config = device_result["config"]

        if enable_clearing:
            candidate_config = clear_config_patterns(
                config=candidate_config, patterns=clear_patterns
            )
        #
        # Some switches always change the parameter synchronization period in their configuration,
        # if you want this not to be taken into account when comparing,
        # enable fix_clock_period in the configuration
        if napalm_driver == "ios" and fix_clock_period is True:
            candidate_config = clear_clock_period_on_device_config(candidate_config)

        # Delete blank line in device configuration
        if fix_double_line_feed:
            # Delete double line feed in device configuration for optimize config compare
            candidate_config = clear_line_feed_on_device_config(config=candidate_config)

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
            "device_id": device_id,
            "vendor": device_result["vendor"],
            "model": device_result["model"],
            "timestamp": str(timestamp),
            "connection_status": error_msg,
            "device_ip": str(ipaddress),
            "last_changed": None,
        }

    # Get device environment
    #
    # Collect device data
    device_info: dict = {
        "device_id": device_id,
        "vendor": device_result["vendor"],
        "model": device_result["model"],
        "timestamp": str(timestamp),
        "connection_status": device_result["connection_status"],
    }
    update_device_env(**device_info)
    device_info["device_ip"] = str(ipaddress)

    # Open last config
    if last_config is None:
        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        status: bool = write_config(
            ipaddress=str(ipaddress), config=str(candidate_config), timestamp=timestamp
        )
        logger.info(f"Config for {ipaddress} save to DB status: {status}")
        device_info["last_changed"] = str(timestamp)
        return device_info

    last_config = last_config["last_config"]
    # Get diff result state if config equals pass
    result_diff = diff_changed(config1=candidate_config, config2=last_config)
    if not result_diff:
        device_info["last_changed"] = str(timestamp)
        status: bool = write_config(
            ipaddress=str(ipaddress), config=str(candidate_config), timestamp=timestamp
        )
        logger.info(f"Config for {ipaddress} save to DB status: {status}")
        return device_info
    device_info["last_changed"] = None
    return device_info
