# import pprint
from pathlib import Path

import urllib3

from nornir import InitNornir

# Import config file
# from nornir.core.inventory import ConnectionOptions

from config import *

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG_FILE = f"{Path(__file__).parent.parent}/config.yaml"
LOGGING = {"log_file": f"{Path(__file__).parent.parent}/logs/log.log", "level": "DEBUG"}


# class nornir_driver:

# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#     def __init__(self):
#         self.USERNAME = USERNAME
#         self.PASSWORD = PASS
#
#     def nornir_driver(self):
#         nr_driver = InitNornir(config_file=CONFIG_FILE, logging=LOGGING)
#         nr_driver.inventory.defaults.username = self.USERNAME
#         nr_driver.inventory.defaults.password = self.PASSWORD
#         return nr_driver


def nornir_driver():
    nr_driver = InitNornir(config_file=CONFIG_FILE, logging=LOGGING)
    nr_driver.inventory.defaults.username = USERNAME
    nr_driver.inventory.defaults.password = PASS

    # print(nr_driver.inventory)
    # for name, host in nr_driver.inventory.hosts.items():
    #     print(f"{name}.username: {host.username}, password: {host.password}, platform: {host.platform}")
    return nr_driver

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
