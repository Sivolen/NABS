#!venv/bin/python3
from datetime import datetime, timedelta
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
# from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config

from nornir.core.exceptions import (
    ConnectionException,
    ConnectionAlreadyOpen,
    ConnectionNotOpen,
    NornirExecutionError,
    NornirSubTaskError,
)
from app import logger
from app.modules.helpers import Helpers

from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    write_device_env,
    update_device_env,
    get_exist_device,
    update_device_status,
    get_device_id,
)

from app.utils import (
    check_ip,
    clear_line_feed_on_device_config,
    clear_clock_period_on_device_config,
)
from app.modules.differ import diff_changed
from config import (
    username,
    password,
    fix_clock_period,
    conn_timeout,
    fix_double_line_feed,
    fix_platform_list,
)

# nr_driver = Helpers()
drivers = Helpers(
    username=username,
    password=password,
    conn_timeout=conn_timeout,
)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


def backup_config_on_db(task: Helpers.nornir_driver) -> None:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    if check_ip(task.host.hostname):
        ip_address = task.host.hostname

        # Get device id from db
        device_id = get_device_id(ipaddress=ip_address)["id"]

        try:
            # Get device information
            device_result = task.run(task=napalm_get, getters=["get_facts", "config"])
        except (
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
        ) as connection_error:
            # Checking device exist on db
            check_device_exist = get_exist_device(device_id=device_id)
            if check_device_exist:
                logger.info(
                    f"An error occurred on Device {device_id} ({ip_address}): {connection_error}"
                )
                update_device_status(
                    device_id=device_id,
                    timestamp=timestamp,
                    connection_status="Connection error",
                )
            else:
                logger.info(
                    f"An error occurred on Device {device_id} ({ip_address}): {connection_error}"
                )
            return
            # Collect device information
        device_info = {
            "hostname": device_result.result["get_facts"]["hostname"],
            "vendor": device_result.result["get_facts"]["vendor"],
            "model": device_result.result["get_facts"]["model"],
            "os_version": device_result.result["get_facts"]["os_version"],
            "sn": device_result.result["get_facts"]["serial_number"],
            "connection_driver": str(task.host.platform),
            "uptime": timedelta(seconds=device_result.result["get_facts"]["uptime"])
        }
        # Check if the serial_number is a list and if it is, take the first element
        if isinstance(device_info["sn"], list) and device_info["sn"] != []:
            device_info["sn"] = device_info["sn"][0]
        else:
            device_info["sn"] = "undefined"

        # Check if device exists in the database
        check_device_exist = get_exist_device(device_id=device_id)

        if check_device_exist:
            # Update device environment
            update_device_env(
                device_id=device_id,
                timestamp=timestamp,
                connection_status="Ok",
                # connection_driver=device_info["platform"],
                **device_info
            )
        else:
            # Write device environment
            write_device_env(
                ipaddress=str(ip_address),
                connection_status="Ok",
                # connection_driver=device_info["connection_driver"],
                **device_info
            )

        # Get the latest configuration file from the database
        last_config = get_last_config_for_device(device_id=device_id)

        # Run the task to get the configuration from the device
        candidate_config = device_result.result["config"]["running"]

        # Fix synchronization period parameter in configuration
        if task.host.platform == "ios" and fix_clock_period is True:
            candidate_config = clear_clock_period_on_device_config(candidate_config)

        # Delete double line feed in configuration
        if task.host.platform in fix_platform_list and fix_double_line_feed is True:
            candidate_config = clear_line_feed_on_device_config(config=candidate_config)

        # Compare candidate configuration with last configuration
        if last_config is not None:
            last_config = last_config["last_config"]
            if not diff_changed(config1=candidate_config, config2=last_config):
                # If the configurations match, don't write to the database
                return
        # Write configuration to the database
        write_config(ipaddress=str(ip_address), config=str(candidate_config))


# This function initializes the nornir driver and starts the configuration backup process.
def run_backup() -> None:
    """
    This function initializes the nornir driver and starts the configuration backup process.
    return:
        None
    """
    # Start process
    try:
        with drivers.nornir_driver_sql() as nr_driver:
            result = nr_driver.run(
                name="Backup configurations", task=backup_config_on_db,
            )
            # Print task result
            print_result(result, vars=["stdout"])
            # if you have error uncomment this row, and you see all result
            # print_result(result)

    except NornirExecutionError as connection_error:
        print(f"Process starts error {connection_error}")


# Main
def main() -> None:
    """
    Main function
    """
    run_backup()


# Start script
if __name__ == "__main__":
    main()
