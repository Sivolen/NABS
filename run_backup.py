#!venv/bin/python3
import re
from datetime import datetime, timedelta
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

# from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config

from modules.helpers import Helpers
from app.utils import (
    get_last_config_for_device,
    write_cfg_on_db,
    write_device_env_on_db,
    update_device_env_on_db,
    get_exist_device_on_db,
    update_device_status_on_db,
)
from modules.differ import diff_get_change_state
from config import username, password, fix_clock_period

# nr_driver = Helpers()
drivers = Helpers(username=username, password=password)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


# Checking ipaddresses
def check_ip(ipaddress: int or str) -> bool:
    pattern = (
        r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1"
        "[0-9]"
        "{2}|2[0-4]["
        "0-9"
        "]|25[0-5])$"
    )
    return True if re.findall(pattern, ipaddress) else False


# The function needed for delete blank line on device config
def clear_blank_line_on_device_config(config: str) -> str:
    # Pattern for replace
    pattern = r"^\n"
    # Return changed config with delete free space
    return re.sub(pattern, "", str(config))


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_clock_period_on_device_config(config: str) -> str:
    # pattern for replace
    pattern = r"ntp\sclock-period\s[0-9]{1,30}\n"
    # Returning changed config or if this command not found return original file
    return re.sub(pattern, "", str(config))


# Start process backup configs
def backup_config_on_db(task: Helpers.nornir_driver) -> None:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    if check_ip(task.host.hostname):
        # Get ip address in task
        ipaddress = task.host.hostname

        # Get the latest configuration file from the database,
        # needed to compare configurations
        last_config = get_last_config_for_device(ipaddress=ipaddress)

        # Run the task to get the configuration from the device
        device_config = task.run(task=napalm_get, getters=["config"])
        device_config = device_config.result["config"]["running"]

        # Some switches always change the parameter synchronization period in their configuration,
        # if you want this not to be taken into account when comparing,
        # enable fix_clock_period in the configuration
        if task.host.platform == "ios" and fix_clock_period is True:
            device_config = clear_clock_period_on_device_config(device_config)

        # Delete blank line in device configuration
        device_config = clear_blank_line_on_device_config(config=device_config)

        # Open last config
        if last_config is not None:
            last_config = last_config["last_config"]
            # Get candidate config from nornir tasks
            candidate_config = device_config
            # Get diff result state if config equals pass
            result = diff_get_change_state(
                config1=candidate_config, config2=last_config
            )
        else:
            result = False

        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        if result is False:
            write_cfg_on_db(ipaddress=str(ipaddress), config=str(device_config))


def get_device_env(task) -> None:
    # device_result = task.run(task=napalm_get, getters=["get_facts", "get_ntp_servers"])
    # Get device environment
    if check_ip(task.host.hostname):
        try:
            device_result = task.run(task=napalm_get, getters=["get_facts"])
            hostname = task.host
            vendor = device_result.result["get_facts"]["vendor"]
            model = device_result.result["get_facts"]["model"]
            os_version = device_result.result["get_facts"]["os_version"]
            sn = device_result.result["get_facts"]["serial_number"]
            platform = task.host.platform
            uptime = timedelta(seconds=device_result.result["get_facts"]["uptime"])

            if type(sn) == list:
                sn = sn[0]

            # Get ip from tasks
            device_ip = task.host.hostname
            check_device_exist = get_exist_device_on_db(ipaddress=device_ip)
            if check_device_exist is True:
                update_device_env_on_db(
                    ipaddress=str(device_ip),
                    hostname=str(hostname),
                    vendor=str(vendor),
                    model=str(model),
                    os_version=str(os_version),
                    sn=str(sn),
                    uptime=str(uptime),
                    timestamp=str(timestamp),
                    connection_status="Ok",
                    connection_driver=str(platform),
                )
            elif check_device_exist is False:
                write_device_env_on_db(
                    ipaddress=str(device_ip),
                    hostname=str(hostname),
                    vendor=str(vendor),
                    model=str(model),
                    os_version=str(os_version),
                    # os_version=str(os_version.decode("utf-8", "ignore")),
                    sn=str(sn),
                    uptime=str(uptime),
                    connection_status="Ok",
                    connection_driver=str(platform),
                )
        except Exception as connection_error:
            device_ip = task.host.hostname
            check_device_exist = get_exist_device_on_db(ipaddress=device_ip)
            if check_device_exist:
                update_device_status_on_db(
                    ipaddress=device_ip,
                    timestamp=timestamp,
                    connection_status=str(connection_error),
                )


def run_backup():
    """
    Main
    """
    # Start process
    with drivers.nornir_driver() as nr_driver:
        result = nr_driver.run(name="Backup configurations", task=backup_config_on_db)
        # Print task result
        print_result(result, vars=["stdout"])

        # if you have error uncomment this row, and you see all result
        # print_result(result)


def run_get_device_env():
    """
    Main
    """
    # Start process
    with drivers.nornir_driver() as nr_driver:
        result = nr_driver.run(name="Get device parm", task=get_device_env)
        # Print task result
        print_result(result, vars=["stdout"])

        # if you have error uncomment this row, and you see all result
        # print_result(result)


def main():
    run_backup()
    run_get_device_env()


if __name__ == "__main__":
    main()
