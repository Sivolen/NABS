#!venv/bin/python3
from datetime import datetime
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
from nornir_netmiko.tasks import netmiko_send_command
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
)
from app import app

drivers = Helpers(conn_timeout=conn_timeout)
# timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")


def custom_backup(
    task: Helpers.nornir_driver, device_id: int, device_ip: str, timestamp:str
) -> dict | None:
    with app.app_context():
        try:
            custom_drivers_id = get_custom_driver_id(device_id=device_id)
            if not custom_drivers_id:
                logger.error(f"No custom driver found for device {device_id}")
                return None

            custom_drivers = get_driver_settings(
                custom_drivers_id=int(custom_drivers_id)
            )
            task.host.platform = custom_drivers["drivers_platform"]
            commands = custom_drivers["drivers_commands"].split(",")

            # Выполняем команды, сохраняя только результат последней
            config = ""
            for command in commands:
                result = task.run(netmiko_send_command, command_string=command)
                config = result.result

            return {
                "vendor": custom_drivers["drivers_vendor"],
                "model": custom_drivers["drivers_model"],
                "config": str(config),
            }

        except (
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
        ) as connection_error:
            logger.error(
                f"Connection error on Device {device_id} ({device_ip}): {connection_error}"
            )
            check_status = log_parser_for_task(ipaddress=device_ip)
            update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=check_status or "Connection error",
            )
            return None


def napalm_backup(
    task: Helpers.nornir_driver, device_id: int, device_ip: str, timestamp:str
) -> dict | None:
    with app.app_context():
        try:
            device_result = task.run(task=napalm_get, getters=["get_facts", "config"])
            return {
                "vendor": device_result.result["get_facts"]["vendor"],
                "model": device_result.result["get_facts"]["model"],
                "config": device_result.result["config"]["running"],
            }
        except (
            ConnectionException,
            ConnectionAlreadyOpen,
            ConnectionNotOpen,
            NornirExecutionError,
            NornirSubTaskError,
        ) as connection_error:
            logger.error(
                f"Connection error on Device {device_id} ({device_ip}): {connection_error}"
            )
            check_status = log_parser_for_task(ipaddress=device_ip)
            update_device_status(
                device_id=device_id,
                timestamp=timestamp,
                connection_status=check_status or "Connection error",
            )
            return None


def backup_config_on_db(task: Helpers.nornir_driver) -> None:
    # Generating timestamp for BD
    # Formatting date time
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    with app.app_context():
        ipaddress: str = task.host.hostname
        if not check_ip(ipaddress):
            logger.warning(f"Invalid IP address: {ipaddress}")
            return

        device_id = get_device_id(ipaddress=ipaddress)
        if not device_id:
            logger.error(f"Device not found in DB: {ipaddress}")
            return
        device_id = int(device_id[0])

        if not get_device_is_enabled(device_id=device_id):
            logger.info(f"Device {ipaddress} is disabled, skipping backup")
            return

        if get_driver_switch_status(device_id=device_id):
            device_result = custom_backup(
                task=task, device_id=device_id, device_ip=ipaddress, timestamp=timestamp
            )
        else:
            device_result = napalm_backup(
                task=task, device_id=device_id, device_ip=ipaddress, timestamp=timestamp
            )

        if not device_result:
            return

        candidate_config = device_result["config"]
        if not candidate_config:
            logger.warning(f"Empty configuration received for {ipaddress}")
            return

        if enable_clearing:
            candidate_config = clear_config_patterns(
                config=candidate_config, patterns=clear_patterns
            )

        if task.host.platform == "ios" and fix_clock_period:
            candidate_config = clear_clock_period_on_device_config(candidate_config)

        if fix_double_line_feed:
            candidate_config = clear_line_feed_on_device_config(candidate_config)

        if len(candidate_config.splitlines()) == 0:
            logger.warning(f"Empty configuration after cleaning for {ipaddress}")
            return

        device_info = {
            "device_id": device_id,
            "vendor": device_result["vendor"],
            "model": device_result["model"],
            "timestamp": timestamp,
            "connection_status": "Ok",
        }
        update_device_env(**device_info)

        last_config = get_last_config_for_device(device_id=device_id)
        if not last_config:
            write_config(ipaddress=ipaddress, config=candidate_config, timestamp=timestamp)
            return

        last_config_content = last_config["last_config"]
        if not diff_changed(config1=candidate_config, config2=last_config_content):
            write_config(ipaddress=ipaddress, config=candidate_config, timestamp=timestamp)


def run_backup() -> None:
    try:
        with drivers.nornir_driver_sql() as nr_driver:
            result = nr_driver.run(
                name="Backup configurations",
                task=backup_config_on_db,
            )
            print_result(result, vars=["stdout"])
    except NornirExecutionError as e:
        logger.error(f"Backup process failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


def main() -> None:
    logger.info("Starting backup process")
    run_backup()
    logger.info("Backup process completed")


if __name__ == "__main__":
    main()
