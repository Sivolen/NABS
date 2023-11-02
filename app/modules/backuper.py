from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from napalm import get_network_driver
from napalm.base.exceptions import (
    NapalmException,
    ConnectionException,
    ConnectAuthError,
    ConnectTimeoutError,
    ConnectionClosedException,
)
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    update_device_env,
    update_device_status,
    get_user_and_pass,
)
from app.modules.dbutils.db_devices import get_device_id

from app import logger

from app.utils import (
    check_ip,
    clear_clock_period_on_device_config,
    clear_line_feed_on_device_config,
)
from config import (
    conn_timeout,
    fix_clock_period,
    fix_double_line_feed,
    fix_platform_list,
)
from app.modules.differ import diff_changed
from app.modules.crypto import decrypt
from config import TOKEN


def backup_runner(napalm_driver: str, ipaddress: str) -> None:
    executor = ThreadPoolExecutor(max_workers=5)
    executor.submit(backup_config_on_db, napalm_driver, ipaddress)


def run_backup_config_on_db(previous_config_data):
    ipaddress = previous_config_data["device"]
    driver = previous_config_data["driver"]
    result = backup_config_on_db(ipaddress=ipaddress, napalm_driver=driver)
    return result


def backup_config_on_db(napalm_driver: str, ipaddress: str) -> dict:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    # Generating timestamp for BD
    now = datetime.now()
    # Formatting date time
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    #
    if not check_ip(ipaddress):
        return logger.info(f"Ipaddress: {ipaddress} is invalid")
    try:
        connect_driver = get_network_driver(napalm_driver)
        device_id = get_device_id(ipaddress=ipaddress)["id"]
        auth_data = get_user_and_pass(device_id=device_id)
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

        # Get device environment
        sn = device_result["serial_number"]
        #
        sn = sn[0] if isinstance(sn, list) and sn != [] else "undefined"
        #
        # Collect device data
        device_info: dict = {
            "device_id": device_id,
            "hostname": device_result["hostname"],
            "vendor": device_result["vendor"],
            "model": device_result["model"],
            "os_version": device_result["os_version"],
            "sn": sn,
            "timestamp": str(timestamp),
            "connection_driver": str(napalm_driver),
            "connection_status": "Ok",
            "uptime": timedelta(seconds=device_result["uptime"]),
        }
        update_device_env(**device_info)

        device_info["device_ip"] = str(ipaddress)
        # Get the latest configuration file from the database,
        # needed to compare configurations
        last_config = get_last_config_for_device(device_id=device_id)

        # Run the task to get the configuration from the device
        device_config = napalm_device.get_config()
        candidate_config = device_config["running"]
        # device_config = task.run(task=napalm_get, getters=["config"])
        # device_config = device_config.result["config"]["running"]
        #
        # Some switches always change the parameter synchronization period in their configuration,
        # if you want this not to be taken into account when comparing,
        # enable fix_clock_period in the configuration
        if napalm_driver == "ios" and fix_clock_period is True:
            candidate_config = clear_clock_period_on_device_config(candidate_config)

        # Delete blank line in device configuration
        # device_config = clear_blank_line_on_device_config(config=device_config)
        if napalm_driver in fix_platform_list and fix_double_line_feed is True:
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
        device_info["last_changed"] = None
        return device_info
    except (
        NapalmException,
        ConnectionException,
        ConnectAuthError,
        ConnectTimeoutError,
        ConnectionClosedException,
    ) as connection_error:
        device_id = get_device_id(ipaddress=ipaddress)["id"]
        device_info = {
            "device_id": device_id,
            "hostname": str(ipaddress),
            "device_ip": str(ipaddress),
            "connection_status": connection_error,
            "vendor": "Vendor not defined",
            "timestamp": str(timestamp),
            "last_changed": None,
        }
        update_device_status(
            device_id=device_id,
            timestamp=timestamp,
            connection_status=str(connection_error),
        )
        return device_info
