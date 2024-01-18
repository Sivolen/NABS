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
)

from app import logger, app
from app.modules.log_parser import log_parser_for_task

from app.utils import (
    check_ip,
    clear_clock_period_on_device_config,
    clear_line_feed_on_device_config,
)
from config import (
    conn_timeout,
    fix_clock_period,
    fix_double_line_feed,
    # fix_platform_list,
)
from app.modules.differ import diff_changed
from app.modules.crypto import decrypt
from config import TOKEN

now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


def backup_runner(napalm_driver: str, ipaddress: str) -> None:
    executor = ThreadPoolExecutor(max_workers=5)
    executor.submit(backup_config_on_db, napalm_driver, ipaddress)


def run_backup_config_on_db(previous_config_data):
    ipaddress = previous_config_data["device"]
    driver = previous_config_data["driver"]
    result = backup_config_on_db(ipaddress=ipaddress, napalm_driver=driver)
    return result


def custom_buckup(ipaddress: str, device_id: int) -> dict | None:
    with app.app_context():
        custom_drivers_id = get_custom_driver_id(device_id=device_id)
        custom_drivers = get_driver_settings(custom_drivers_id=int(custom_drivers_id))
        auth_data = get_user_and_pass(device_id=device_id)
        task = {
            "device_type": custom_drivers["drivers_platform"],
            "host": ipaddress,
            "username": auth_data["credentials_username"],
            "password": decrypt(auth_data["credentials_password"], key=TOKEN),
            "port": auth_data["ssh_port"],
            "conn_timeout": conn_timeout,
        }
        try:
            with ConnectHandler(**task) as ssh:
                for command in custom_drivers["drivers_commands"].split(","):
                    config = ssh.send_command(command_string=command)
        except (
            NetmikoTimeoutException,
            NetmikoAuthenticationException,
        ) as connection_error:
            logger.info(
                f"An error occurred on Device {device_id} ({ipaddress}): {connection_error}"
            )
            # Checking device exist on db
            check_status = log_parser_for_task(ipaddress=ipaddress)
            update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=check_status
                if check_status is not None
                else "Connection error",
            )
            return {
                "connection_status": connection_error,
                "vendor": "Vendor not defined",
                "model": None,
                "last_changed": None,
                "config": None,
            }

        return {
            "connection_status": "Ok",
            "vendor": custom_drivers["drivers_vendor"],
            "model": custom_drivers["drivers_model"],
            "config": str(config),
        }


def napalm_backup(ipaddress: str, device_id: int, napalm_driver: str):
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
    # Generating timestamp for BD
    #
    if not check_ip(ipaddress):
        return logger.info(f"Ipaddress: {ipaddress} is invalid")
    #
    device_id = get_device_id(ipaddress=ipaddress)
    if not device_id:
        return logger.info(f"Device id: {ipaddress} is invalid")
    device_id = int(device_id[0])
    #
    # Run the task to get the configuration from the device
    if get_driver_switch_status(device_id=device_id):
        device_result = custom_buckup(ipaddress=ipaddress, device_id=device_id)
    else:
        device_result = napalm_backup(
            ipaddress=ipaddress, device_id=device_id, napalm_driver=napalm_driver
        )
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
    if device_result["config"] is None:
        device_info["device_ip"] = str(ipaddress)
        device_info["last_changed"] = None
        return device_info

    candidate_config = device_result["config"]
    update_device_env(**device_info)

    device_info["device_ip"] = str(ipaddress)
    # Get the latest configuration file from the database,
    # needed to compare configurations
    last_config = get_last_config_for_device(device_id=device_id)
    #
    # Some switches always change the parameter synchronization period in their configuration,
    # if you want this not to be taken into account when comparing,
    # enable fix_clock_period in the configuration
    if napalm_driver == "ios" and fix_clock_period is True:
        candidate_config = clear_clock_period_on_device_config(candidate_config)

    # Delete blank line in device configuration
    # device_config = clear_blank_line_on_device_config(config=device_config)
    if fix_double_line_feed:
        # Delete double line feed in device configuration for optimize config compare
        candidate_config = clear_line_feed_on_device_config(config=candidate_config)

    # Open last config
    if last_config is None:
        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        write_config(ipaddress=str(ipaddress), config=str(candidate_config))
        device_info["last_changed"] = str(timestamp)
        return device_info

    last_config = last_config["last_config"]
    # Get diff result state if config equals pass
    result_diff = diff_changed(config1=candidate_config, config2=last_config)
    if not result_diff:
        device_info["last_changed"] = str(timestamp)
        write_config(ipaddress=str(ipaddress), config=str(candidate_config))
        return device_info
    device_info["last_changed"] = None
    return device_info
