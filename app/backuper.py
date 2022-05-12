import re
from datetime import datetime, timedelta

from napalm import get_network_driver
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

from modules.helpers import Helpers
from config import username, password, fix_clock_period
from modules.differ import diff_changed

from app.utils import (
    get_last_config_for_device,
    write_cfg_on_db,
    write_device_env_on_db,
    update_device_env_on_db,
    get_exist_device_on_db,
    update_device_status_on_db,
)
from napalm.base.exceptions import (
    NapalmException,
    ConnectionException,
    ConnectAuthError,
    ConnectTimeoutError,
    ConnectionClosedException,
)

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


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_clock_period_on_device_config(config: str) -> str:
    # pattern for replace
    pattern = r"ntp\sclock-period\s[0-9]{1,30}\n"
    # Returning changed config or if this command not found return original file
    return re.sub(pattern, "", str(config))


# The function needed for delete blank line on device config
def clear_blank_line_on_device_config(config: str) -> str:
    # Pattern for replace
    pattern = r"^\n"
    # Return changed config with delete free space
    return re.sub(pattern, "", str(config))


def napalm_connect(napalm_driver, ipaddress, napalm_sn=None):
    pass


def backup_config_on_db(napalm_driver: str, ipaddress: str) -> dict:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    result_dict = {
        "ipaddress": None,
        "hostname": None,
        "vendor": None,
        "model": None,
        "os_version": None,
        "sn": None,
        "uptime": None,
        "timestamp": None,
        "connection_status": None,
        "connection_driver": None,
        "last_changed": None
    }
    napalm_device = None
    if check_ip(ipaddress):
        try:
            connect_driver = get_network_driver(napalm_driver)
            napalm_device = connect_driver(
                hostname=ipaddress,
                username=username,
                password=password,
                optional_args={"port": 22},
            )
            napalm_device.open()
            device_result = napalm_device.get_facts()

            # Get device environment
            hostname = device_result["hostname"]
            vendor = device_result["vendor"]
            model = device_result["model"]
            os_version = device_result["os_version"]
            sn = device_result["serial_number"]
            platform = napalm_driver
            uptime = timedelta(seconds=device_result["uptime"])
            #
            if type(sn) == list:
                sn = sn[0]
            #
            # Get ip from tasks
            check_device_exist = get_exist_device_on_db(ipaddress=ipaddress)
            if check_device_exist is True:
                update_device_env_on_db(
                    ipaddress=str(ipaddress),
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
                result_dict.update(
                    {
                        "ipaddress": str(ipaddress),
                        "hostname": str(hostname),
                        "vendor": str(vendor),
                        "model": str(model),
                        "os_version": str(os_version),
                        "sn": str(sn),
                        "uptime": str(uptime),
                        "timestamp": str(timestamp),
                        "connection_status": "Ok",
                        "connection_driver": str(platform),
                    }

                )
            elif check_device_exist is False:
                write_device_env_on_db(
                    ipaddress=str(ipaddress),
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
        except (
            NapalmException,
            ConnectionException,
            ConnectAuthError,
            ConnectTimeoutError,
            ConnectionClosedException,
        ) as connection_error:
            check_device_exist = get_exist_device_on_db(ipaddress=ipaddress)
            if check_device_exist:
                update_device_status_on_db(
                    ipaddress=ipaddress,
                    timestamp=timestamp,
                    connection_status=str(connection_error),
                )

        # Get the latest configuration file from the database,
        # needed to compare configurations
        last_config = get_last_config_for_device(ipaddress=ipaddress)

        # Run the task to get the configuration from the device
        device_config = napalm_device.get_config()
        device_config = device_config["running"]
        # device_config = task.run(task=napalm_get, getters=["config"])
        # device_config = device_config.result["config"]["running"]
        #
        # Some switches always change the parameter synchronization period in their configuration,
        # if you want this not to be taken into account when comparing,
        # enable fix_clock_period in the configuration
        if napalm_driver == "ios" and fix_clock_period is True:
            device_config = clear_clock_period_on_device_config(device_config)

        # Delete blank line in device configuration
        device_config = clear_blank_line_on_device_config(config=device_config)

        # Open last config
        if last_config is not None:
            last_config = last_config["last_config"]
            # Get candidate config from nornir tasks
            candidate_config = device_config
            # Get diff result state if config equals pass
            result = diff_changed(config1=candidate_config, config2=last_config)
        else:
            result = False

        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        if result is False:
            write_cfg_on_db(ipaddress=str(ipaddress), config=str(device_config))
            result_dict.update(
                {
                    "last_changed": str(timestamp)
                }
            )
    return result_dict


def run_backup(ipaddress: str = None) -> None:
    """
    Main
    """
    # Start process
    drivers = Helpers(username=username, password=password, ipaddress=ipaddress)
    try:
        with drivers.nornir_driver_sql() as nr_driver:
            result = nr_driver.run(
                name="Backup configurations", task=backup_config_on_db
            )
            # Print task result
            print_result(result, vars=["stdout"])
            # if you have error uncomment this row, and you see all result
            # print_result(result)

    # if you have error uncomment this row, and you see all result
    # print_result(result)
    except Exception as connection_error:
        print(f"Process starts error {connection_error}")


if __name__ == "__main__":
    backup_config_on_db(ipaddress="10.255.100.1", napalm_driver="ce")
