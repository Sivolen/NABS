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

from app.modules.helpers import Helpers

from app.modules.dbutils import (
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
    clear_blank_line_on_device_config,
    clear_clock_period_on_device_config,
)
from app.modules.differ import diff_changed
from config import username, password, fix_clock_period, conn_timeout

# nr_driver = Helpers()
drivers = Helpers(username=username, password=password, conn_timeout=conn_timeout)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


# Start process backup configs
def backup_config_on_db(task: Helpers.nornir_driver) -> None:
    """
    This function starts to process backup config on the network devices
    Need for work nornir task
    """
    if check_ip(task.host.hostname):

        # Get ip address in task
        ipaddress = task.host.hostname
        device_id = get_device_id(ipaddress=ipaddress)["id"]

        # Get device environment
        try:
            device_result = task.run(task=napalm_get, getters=["get_facts"])
            hostname = device_result.result["get_facts"]["hostname"]
            vendor = device_result.result["get_facts"]["vendor"]
            model = device_result.result["get_facts"]["model"]
            os_version = device_result.result["get_facts"]["os_version"]
            sn = device_result.result["get_facts"]["serial_number"]
            platform = task.host.platform
            uptime = timedelta(seconds=device_result.result["get_facts"]["uptime"])

            if isinstance(sn, list):
                sn = sn[0]

            # Get ip from tasks
            check_device_exist = get_exist_device(device_id=device_id)
            if check_device_exist is True:
                update_device_env(
                    device_id=device_id,
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
                write_device_env(
                    ipaddress=str(ipaddress),
                    hostname=str(hostname),
                    vendor=str(vendor),
                    model=str(model),
                    os_version=str(os_version),
                    sn=str(sn),
                    uptime=str(uptime),
                    connection_status="Ok",
                    connection_driver=str(platform),
                )
        except (
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
        ) as connection_error:
            ipaddress = task.host.hostname
            check_device_exist = get_exist_device(device_id=device_id)
            if check_device_exist:
                update_device_status(
                    device_id=device_id,
                    timestamp=timestamp,
                    connection_status=str(connection_error),
                )

        # Get the latest configuration file from the database,
        # needed to compare configurations
        last_config = get_last_config_for_device(device_id=device_id)

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
            result = diff_changed(config1=candidate_config, config2=last_config)
        else:
            result = False

        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
        if result is False:
            write_config(ipaddress=str(ipaddress), config=str(device_config))


def run_backup():
    """
    Main
    """
    # Start process
    try:
        with drivers.nornir_driver_sql() as nr_driver:
            result = nr_driver.run(
                name="Backup configurations", task=backup_config_on_db
            )
            # Print task result
            print_result(result, vars=["stdout"])
            # if you have error uncomment this row, and you see all result
            # print_result(result)

    except Exception as connection_error:
        print(f"Process starts error {connection_error}")


def main():
    run_backup()


if __name__ == "__main__":
    main()
