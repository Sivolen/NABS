#!venv/bin/python3
from datetime import datetime
from nornir_utils.plugins.functions import print_result

from app import logger

from app.modules.helpers import Helpers

from app.modules.dbutils.db_utils import (
    get_device_id,
    add_device,
)

from app.modules.dbutils.db_groups import check_device_group, add_device_group

from app.utils import (
    check_ip,
)

from config import conn_timeout, username, password


# nr_driver = Helpers()
drivers = Helpers(conn_timeout=conn_timeout)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


# Start process backup configs
def netbox_import(task: Helpers.nornir_driver) -> None:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    # print(task.host)
    # print(task.host.data["device_role"]["name"])
    # print(task.host.data.manufacturer)
    if not check_ip(task.host.hostname):
        return

    # Get ip address in task
    ipaddress = task.host.hostname
    # Get device id from db
    device_id = get_device_id(ipaddress=ipaddress)
    #
    if device_id is not None or task.host.platform is None:
        return
    if device_id is None and task.host.platform is None:
        return
    try:
        group_id = check_device_group(task.host.data["device_role"]["name"])
        if group_id is not None:
            return
        result = add_device_group(group_name=task.host.data["device_role"]["name"])
        if not result:
            logger.info(f'Add group {task.host.data["device_role"]["name"]}: Error')

        logger.info(f'Add group {task.host.data["device_role"]["name"]}: success')

        group_id = check_device_group(task.host.data["device_role"]["name"])

        device_data = {
            "group_id": group_id,
            "hostname": str(task.host),
            "ipaddress": str(ipaddress),
            "connection_driver": str(task.host.platform),
            "ssh_port": 22,
            "ssh_user": username,
            "ssh_pass": password,
        }
        add_device(**device_data)
    except Exception as import_error:
        logger.info(f"An error occurred on Device {ipaddress}: {import_error}")


def run_netbox_import():
    """
    Main
    """
    # Start process
    with drivers.nornir_driver() as nr_driver:
        result = nr_driver.run(name="NetBox Import", task=netbox_import)
        # Print task result
        print_result(result, vars=["stdout"])

        # if you have error uncomment this row, and you see all result
        # print_result(result)


def main():
    run_netbox_import()


if __name__ == "__main__":
    main()
