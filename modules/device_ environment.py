# import os
import pprint

# from datetime import datetime
# from pathlib import Path
from helpers import helpers
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

# from nornir_utils.plugins.tasks.files import write_file

from config import *

drivers = helpers(username=username, password=password)

list = []


def get_device_env(task) -> None:
    device_result = task.run(task=napalm_get, getters=["get_facts", "get_ntp_servers"])
    pprint.pprint(f"{task.host} {device_result.result['get_facts']['serial_number']}")
    pprint.pprint(f"{task.host} {device_result.result['get_facts']['os_version']}")
    pprint.pprint(f"{task.host} {device_result.result['get_ntp_servers']}")
    result = {
        "hostname": task.host,
        "ip_address": task.host.hostname,
        "serial": device_result.result["get_facts"]["serial_number"],
    }
    return list.append(result)


def main():
    """
    Main
    """
    # Start process
    with drivers.nornir_driver() as nr_driver:
        result = nr_driver.run(name="Get device parm", task=get_device_env)
        # Print task result
        print_result(result, vars=["stdout"])

        print(list)

        # if you have error uncomment this row, and you see all result
        # print_result(result)


if __name__ == "__main__":
    main()
