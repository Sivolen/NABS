from pathlib import Path

import urllib3

from nornir import InitNornir
# from nornir.core.inventory import ConnectionOptions

# Import config file
from config import *

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG_FILE = f"{Path(__file__).parent.parent}/config.yaml"
LOGGING = {"log_file": f"{Path(__file__).parent.parent}/logs/log.log", "level": "DEBUG"}


def nornir_driver():
    nr_driver = InitNornir(config_file=CONFIG_FILE, logging=LOGGING)
    nr_driver.inventory.defaults.username = USERNAME
    nr_driver.inventory.defaults.password = PASS
    # nr_driver.inventory.defaults.connection_options["netmiko"] = ConnectionOptions(
    #     extras={
    #         "timeout": 30,
    #         "conn_timeout": 30,
    #         'use_keys': False,
    #         'blocking_timeout': 30,
    #     },
    # )
    # nr_driver.inventory.defaults.connection_options["paramiko"] = ConnectionOptions(
    #     extras={
    #         "timeout": 30,
    #         "conn_timeout": 30,
    #         'use_keys': False,
    #     },
    # )
    return nr_driver
