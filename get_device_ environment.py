#!/home/agridnev/PycharmProjects/netbox_config_backup/venv/bin/python3
# import os
# import pprint

from datetime import datetime, timedelta

# from pathlib import Path
from modules.helpers import Helpers
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
from app.utils import (
    get_exist_device_on_db,
    update_device_env_on_db,
    write_device_env_on_db,
)

# from nornir_utils.plugins.tasks.files import write_file

from config import *

drivers = Helpers(username=username, password=password)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


def get_device_env(task) -> None:
    # device_result = task.run(task=napalm_get, getters=["get_facts", "get_ntp_servers"])
    # Get device environment
    device_result = task.run(task=napalm_get, getters=["get_facts"])

    hostname = task.host
    vendor = device_result.result["get_facts"]["vendor"]
    model = device_result.result["get_facts"]["model"]
    os_version = device_result.result["get_facts"]["os_version"]
    sn = device_result.result["get_facts"]["serial_number"]
    uptime = timedelta(seconds=device_result.result["get_facts"]["uptime"])

    if type(sn) == list:
        sn = sn[0]

    # Get ip from tasks
    device_ip = task.host.hostname
    check_device_exist = get_exist_device_on_db(ipaddress=device_ip)
    if check_device_exist is True:
        update_device_env_on_db(
            ipaddress=device_ip,
            hostname=str(hostname),
            vendor=vendor,
            model=model,
            os_version=os_version,
            sn=str(sn),
            uptime=str(uptime),
            timestamp=timestamp,
        )
    elif check_device_exist is False:
        write_device_env_on_db(
            ipaddress=device_ip,
            hostname=str(hostname),
            vendor=vendor,
            model=model,
            os_version=os_version,
            sn=str(sn),
            uptime=str(uptime),
        )


def main():
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


if __name__ == "__main__":
    main()
