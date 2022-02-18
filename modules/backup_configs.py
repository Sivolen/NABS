import os

# import pprint
import re
from datetime import datetime
from pathlib import Path
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
from nornir_utils.plugins.tasks.files import write_file

# from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config

from helpers import helpers
from web_app.app_helper import write_cfg_on_db, get_last_config_for_device
from path_helper import search_configs_path
from differ import diff_get_change_state
from config import *

# nr_driver = helpers()
drivers = helpers(username=username, password=password)
search_configs_path = search_configs_path()

configs_folder_path = f"{Path(__file__).parent.parent}/configs"

# Get time for configs name
timestamp = datetime.now()


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_clock_period(config: str) -> str:
    # pattern for replace
    pattern = r"ntp\sclock-period\s[0-9]{1,30}\n"
    # Returning changed config or if this command not found return original file
    return re.sub(pattern, "", str(config))


# Start process backup configs
def backup_config(task, path):
    """
    This function starts to process backup config on the network devices
    """
    # Get ip address in task
    ipaddress = task.host.hostname
    # Get Last config dict
    last_config = search_configs_path.get_lats_config_for_device(ipaddress=ipaddress)
    # Start task and get config on device
    device_config = task.run(task=napalm_get, getters=["config"])
    device_config = device_config.result["config"]["running"]

    if task.host.platform == "ios" and fix_clock_period is True:
        device_config = clear_clock_period(device_config)

    # Open last config
    if last_config is not None:
        last_config = open(last_config["config_path"])
        # Get candidate config from nornir tasks
        candidate_config = device_config
        # Get diff result state if config equals pass
        result = diff_get_change_state(
            config1=candidate_config, config2=last_config.read()
        )
        # Close last config file
        last_config.close()
    else:
        result = False

    # If configs not equals
    if result is False:
        # Create directory for configs
        if not os.path.exists(
            f"{path}/{timestamp.date()}_{timestamp.hour}-{timestamp.minute}"
        ):
            os.mkdir(f"{path}/{timestamp.date()}_{timestamp.hour}-{timestamp.minute}")

        # Startt task for write cfg file
        task.run(
            task=write_file,
            content=device_config,
            filename=f"{path}/{timestamp.date()}_{timestamp.hour}-{timestamp.minute}/{task.host.hostname}.cfg",
        )


# Start process backup configs
def backup_config_on_db(task):
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

    if task.host.platform == "ios" and fix_clock_period is True:
        device_config = clear_clock_period(device_config)

    # Open last config
    if last_config is not None:
        last_config = last_config["last_config"]
        # Get candidate config from nornir tasks
        candidate_config = device_config
        # Get diff result state if config equals pass
        result = diff_get_change_state(config1=candidate_config, config2=last_config)
    else:
        result = False

    # If configs not equals
    if result is False:
        write_cfg_on_db(ipaddress=str(ipaddress), config=str(device_config))


def main():
    """
    Main
    """
    # Start process
    with drivers.nornir_driver() as nr_driver:
        result = nr_driver.run(
            name="Backup configurations", path=configs_folder_path, task=backup_config
        )
        # Print task result
        print_result(result, vars=["stdout"])

        # if you have error uncomment this row, and you see all result
        # print_result(result)


def main2():
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


if __name__ == "__main__":
    main2()
