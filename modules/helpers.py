import pprint

import urllib3

from pathlib import Path

from nornir import InitNornir
from nornir.core.inventory import ConnectionOptions

# from nornir.core import inventory

from config import DBHost, DBPort, DBName, DBUser, DBPassword


class Helpers:
    """Class nornir drivers for network automation system"""

    # Disable https crt warning
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Init class param
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

        # Get config file
        if self.config_file is None:
            self.config_file = f"{Path(__file__).parent.parent}/config.yaml"

        # Get logs directory
        if self.logging_file is None:
            self.logging_file = {
                "log_file": f"{Path(__file__).parent.parent}/logs/log.log",
                "level": "DEBUG",
            }

    # Put config or parameters for Nornir
    def nornir_driver(self) -> InitNornir:
        """
        InitNornir
        """
        # Put in nornir config file
        nr_driver = InitNornir(config_file=self.config_file, logging=self.logging_file)
        # Put in nornir cli username
        # Put in nornir cli password
        nr_driver.inventory.defaults.password = self.password

        # Change default connection timers
        nr_driver.inventory.defaults.connection_options["napalm"] = ConnectionOptions(
            extras={"optional_args": {"conn_timeout": self.conn_timeout}}
        )
        pprint.pprint(nr_driver.inventory.dict())
        return nr_driver

    def nornir_driver_sql(self) -> InitNornir:
        """
        InitNornir
        """
        hosts_query = """\
        SELECT device_hostname AS name, device_ip AS hostname, connection_driver AS platform 
        FROM Devices
        """
        # WHERE status='deployed'

        inventory = {
            "plugin": "SQLInventory",
            "options": {
                "sql_connection": f"postgresql://{DBUser}:{DBPassword}@{DBHost}:{DBPort}/{DBName}",
                "hosts_query": hosts_query,
            },
        }

        nr_driver = InitNornir(inventory=inventory, logging=self.logging_file)
        # Put in nornir config file
        # nr_driver = InitNornir(config_file=self.config_file, logging=self.logging_file)
        # Put in nornir cli username
        nr_driver.inventory.defaults.username = self.username
        # Put in nornir cli password
        nr_driver.inventory.defaults.password = self.password

        # Change default connection timers
        nr_driver.inventory.defaults.connection_options["napalm"] = ConnectionOptions(
            extras={"optional_args": {"conn_timeout": self.conn_timeout}}
        )
        return nr_driver
