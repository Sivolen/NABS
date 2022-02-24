from pathlib import Path

import urllib3

from nornir import InitNornir

# Import config file
from nornir.core.inventory import ConnectionOptions


class Helpers:
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
        """
        Init Class
        """
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
