#!/home/agridnev/PycharmProjects/netbox_config_backup/venv/bin/python3
import re
from datetime import datetime
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

# from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config

from modules.helpers import Helpers
from app.utils import get_last_config_for_device, write_cfg_on_db
from modules.differ import diff_get_change_state
from config import username, password, fix_clock_period

# nr_driver = Helpers()
drivers = Helpers(username=username, password=password)

# Get time for configs name
timestamp = datetime.now()


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


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
        result = diff_get_change_state(config1=candidate_config, config2=last_config)
    else:
        result = False

    # If the configs do not match or there are changes in the config,
    # save the configuration to the database
    if result is False:
        write_cfg_on_db(ipaddress=str(ipaddress), config=str(device_config))


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


def main():
    run_backup()


if __name__ == "__main__":
    main()
