#!venv/bin/python3
from datetime import datetime
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

from nornir_netmiko.tasks import netmiko_send_command

# from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config

from nornir.core.exceptions import (
    ConnectionException,
    ConnectionAlreadyOpen,
    ConnectionNotOpen,
    NornirExecutionError,
    NornirSubTaskError,
)
from app import logger
from app.modules.dbutils.db_drivers import get_driver_settings
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

# from app.modules.dbengine import get_device_id
from app.modules.log_parser import log_parser_for_task

from app.utils import (
    check_ip,
    clear_line_feed_on_device_config,
    clear_clock_period_on_device_config,
    clear_config_patterns,
)
from app.modules.differ import diff_changed
from config import (
    fix_clock_period,
    conn_timeout,
    fix_double_line_feed,
    enable_clearing,
    clear_patterns,
    # fix_platform_list,
)

from app import app


# nr_driver = Helpers()
drivers = Helpers(conn_timeout=conn_timeout)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


def custom_buckup(
    task: Helpers.nornir_driver, device_id: int, device_ip: str
) -> dict | None:
    with app.app_context():
        config = None
        custom_drivers_id = get_custom_driver_id(device_id=device_id)
        custom_drivers = get_driver_settings(custom_drivers_id=int(custom_drivers_id))
        task.host.platform = custom_drivers["drivers_platform"]
        commands: list = custom_drivers["drivers_commands"].split(",")
        try:
            for i, command in enumerate(commands):
                if not command:
                    logger.warning(
                        f"Empty command found for Device {device_id} ({task.host.hostname}). Skipping."
                    )
                    continue
                try:
                    current_config = netmiko_send_command(task, command_string=command)
                    # We save the output of only the last command
                    if i == len(commands) - 1:
                        config = current_config
                except OSError as os_error:
                    # Handling the error "Search pattern never detected"
                    logger.error(
                        f"Error on Device {device_id} ({task.host.hostname}): Incorrect driver configuration. "
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
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
        ) as connection_error:
            logger.info(
                f"An error occurred on Device {device_id} ({device_ip}): {connection_error}"
            )
            # Checking device exist on db
            check_status = log_parser_for_task(ipaddress=device_ip)
            update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=check_status
                if check_status is not None
                else "Connection error",
            )
            return
        return {
            "vendor": custom_drivers["drivers_vendor"],
            "model": custom_drivers["drivers_model"],
            "config": str(config),
        }


def napalm_backup(
    task: Helpers.nornir_driver, device_id: int, device_ip: str
) -> dict | None:
    with app.app_context():
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
            logger.info(
                f"An error occurred on Device {device_id} ({device_ip}): {connection_error}"
            )
            check_status = log_parser_for_task(ipaddress=device_ip)
            update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=check_status
                if check_status is not None
                else "Connection error",
            )
            return
        return {
            "vendor": device_result.result["get_facts"]["vendor"],
            "model": device_result.result["get_facts"]["model"],
            "config": device_result.result["config"]["running"],
        }


# Start process backup configs
def backup_config_on_db(task: Helpers.nornir_driver) -> None:
    """
    This function starts a backup of the network equipment configuration
    Need for work nornir task
    """
    with app.app_context():
        # Get ip address in task
        ipaddress: str = task.host.hostname
        if not check_ip(ipaddress):
            return
        # Get device id from db
        device_id = get_device_id(ipaddress=ipaddress)
        if not device_id:
            return
        device_id = int(device_id[0])
        # check if device is enabled
        if not get_device_is_enabled(device_id=device_id):
            return
        # device_id: int = get_device_id(ipaddress=ipaddress)[0]
        #
        # Run the task to get the configuration from the device
        if get_driver_switch_status(device_id=device_id):
            device_result = custom_buckup(
                task=task, device_id=int(device_id), device_ip=ipaddress
            )
        else:
            device_result = napalm_backup(
                task=task, device_id=int(device_id), device_ip=ipaddress
            )

        if not device_result:
            return
        device_info = {
            "device_id": device_id,
            "vendor": device_result["vendor"],
            "model": device_result["model"],
            "timestamp": str(timestamp),
            "connection_status": "Ok",
        }

        # device_config = task.run(task=napalm_get, getters=["config"])
        # candidate_config = device_config.result["config"]["running"]
        candidate_config: str = device_result["config"]
        update_device_env(**device_info)

        # Get the latest configuration file from the database,
        # needed to compare configurations
        last_config: dict = get_last_config_for_device(device_id=device_id)

        # Some switches always change the parameter synchronization period in their configuration,
        # if you want this not to be taken into account when comparing,
        # enable fix_clock_period in the configuration
        if enable_clearing:
            candidate_config = clear_config_patterns(
                config=candidate_config, patterns=clear_patterns
            )
        if task.host.platform == "ios" and fix_clock_period is True:
            candidate_config = clear_clock_period_on_device_config(candidate_config)
        if fix_double_line_feed:
            # Delete double line feed in device configuration for optimize config compare
            candidate_config = clear_line_feed_on_device_config(config=candidate_config)

        # Test option if config line == 0
        if len(candidate_config.splitlines()) == 0:
            return

        # Open last config
        if last_config is None:
            write_config(
                ipaddress=str(ipaddress),
                config=str(candidate_config),
                timestamp=timestamp,
            )
            return
            # If the configs do not match or there are changes in the config,
            # save the configuration to the database
        last_config: str = last_config["last_config"]
        # Get diff result state if config equals pass
        diff_result = diff_changed(config1=candidate_config, config2=last_config)
        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        if not diff_result:
            write_config(
                ipaddress=str(ipaddress),
                config=str(candidate_config),
                timestamp=timestamp,
            )

        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        # if result is False:
        #     write_config(ipaddress=str(ipaddress), config=str(device_config))


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
                name="Backup configurations",
                task=backup_config_on_db,
            )
            # Print task result
            print_result(result, vars=["stdout"])
            # print_result(result, vars=["exception"])
            # print_result(result, vars=["host"])
            # print(result.failed_hosts.keys())
            # for result in result.failed_hosts.keys():
            #     update_connection_status(hostname=result)
            # print(result["yzh-kpr32-kvo-psw01"][1].exception)
            # try:
            #     result.raise_on_error()
            # except NornirExecutionError as e:
            #     print(f"ERROR!!! {e}")
            # if you have error uncomment this row, and you see all result
            # print_result(result)
    except NornirExecutionError as connection_error:
        logger.debug(f"Process starts error {connection_error}")


# Main
def main() -> None:
    """
    Main function
    """
    logger.info(f"The backup code process has been initiated")
    run_backup()


# Start script
if __name__ == "__main__":
    main()
