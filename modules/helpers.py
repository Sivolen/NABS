# import pprint
from pathlib import Path

import urllib3

from nornir import InitNornir

# Import config file
from nornir.core.inventory import ConnectionOptions


# from config import *

# config_file = f"{Path(__file__).parent.parent}/config.yaml"
# logging_file = {"log_file": f"{Path(__file__).parent.parent}/logs/log.log", "level": "DEBUG"}

# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class helpers:
    """Class nornir drivers for NetBox network tools"""

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def __init__(
        self,
        username,
        password,
        conn_timeout=10,
        config_file=None,
        logging_file=None,
    ):
        self.username = username
        self.password = password
        self.conn_timeout = conn_timeout
        self.config_file = config_file
        self.logging_file = logging_file

        if self.config_file is None:
            self.config_file = f"{Path(__file__).parent.parent}/config.yaml"

        if self.logging_file is None:
            self.logging_file = {
                "log_file": f"{Path(__file__).parent.parent}/logs/log.log",
                "level": "DEBUG",
            }


    def nornir_driver(self):
        """
        InitNornir
        """
        nr_driver = InitNornir(config_file=self.config_file, logging=self.logging_file)
        nr_driver.inventory.defaults.username = self.username
        nr_driver.inventory.defaults.password = self.password

        # Change default connection timers
        nr_driver.inventory.defaults.connection_options["napalm"] = ConnectionOptions(
            extras={"optional_args": {"conn_timeout": self.conn_timeout}}
        )

        return nr_driver



# def helpers():
#     nr_driver = InitNornir(config_file=config_file, logging=logging_file)
#     nr_driver.inventory.defaults.username = username
#     nr_driver.inventory.defaults.password = password
#
#     # print(nr_driver.inventory)
#     # for name, host in nr_driver.inventory.hosts.items():
#     #     print(f"{name}.username: {host.username}, password: {host.password}, platform: {host.platform}")
#
#     # Change default connection timers
#     nr_driver.inventory.defaults.connection_options["napalm"] = ConnectionOptions(
#         extras={"optional_args": {"conn_timeout": 10}})
#
#     return nr_driver
