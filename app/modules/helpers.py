import urllib3
from urllib3 import exceptions

from pathlib import Path

from nornir import InitNornir
from nornir.core.inventory import ConnectionOptions
from nornir.core.plugins.inventory import (
    InventoryPluginRegister,
    TransformFunctionRegister,
)
from nornir.core.inventory import Host

from app.modules.crypto import decrypt
from app.modules.plugin.sql import SQLInventoryCrypto

from config import DBHost, DBPort, DBName, DBUser, DBPassword, TOKEN


def _decrypt_passwords(host: Host, key: str):
    host.password = decrypt(host.password, key)


class Helpers:
    """Class nornir drivers for network automation system"""

    # Disable https crt warning
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # Register custom nornir plugin for crypto ssh password
    plugin_register = InventoryPluginRegister.register
    plugin_register(name="SQLInventoryCrypto", plugin=SQLInventoryCrypto)

    TransformFunctionRegister.register("decrypt_passwords", _decrypt_passwords)

    # Init class param
    def __init__(
        self,
        username=None,
        password=None,
        conn_timeout=10,
        config_file=None,
        logging_file=None,
        ipaddress=None,
    ):
        """
        Init Class
        """
        self.username = username
        self.password = password
        self.conn_timeout = conn_timeout
        self.config_file = config_file
        self.logging_file = logging_file
        self.ipaddress = ipaddress

        # Get config file
        if self.config_file is None:
            self.config_file = (
                f"{Path(__file__).parent.parent.parent}/netbox_config.yaml"
            )

        # Get logs directory
        if self.logging_file is None:
            self.logging_file = {
                "log_file": f"{Path(__file__).parent.parent.parent}/logs/log.log",
                "level": "DEBUG",
            }

    # Put config or parameters for Nornir
    def nornir_driver(self) -> InitNornir:
        """
        InitNornir
        """
        # Put in nornir config file
        nr_driver = InitNornir(config_file=self.config_file, logging=self.logging_file)
        if self.username and self.password is not None:
            # Put in nornir cli username
            nr_driver.inventory.defaults.username = self.username
            # Put in nornir cli password
            nr_driver.inventory.defaults.password = self.password

        # Change default connection timers
        nr_driver.inventory.defaults.connection_options["napalm"] = ConnectionOptions(
            extras={"optional_args": {"conn_timeout": self.conn_timeout}}
        )
        return nr_driver

    def nornir_driver_sql(self) -> InitNornir:
        """
        InitNornir
        """

        if self.ipaddress is None:
            hosts_query = """\
            SELECT device_hostname AS name, device_ip AS hostname, connection_driver AS platform, 
            ssh_user as username, ssh_pass as password, ssh_port as port
            FROM Devices
            """
        else:
            # WHERE status='deployed'
            hosts_query = f"""\
            SELECT device_hostname AS name, device_ip AS hostname, connection_driver AS platform, 
            ssh_user as username, ssh_pass as password, ssh_port as port
            FROM Devices
            WHERE device_ip='{self.ipaddress}'
            """
        inventory = {
            "plugin": "SQLInventory",
            # "plugin": "SQLInventoryCrypto",
            "options": {
                "sql_connection": f"postgresql://{DBUser}:{DBPassword}@{DBHost}:{DBPort}/{DBName}",
                "hosts_query": hosts_query,
                # "crypto_token": TOKEN,
            },
            "transform_function": "decrypt_passwords",
            "transform_function_options": {"key": TOKEN},
        }
        runner = {
            "plugin": "threaded",
            "options": {
                "num_workers": 20,
            },
        }
        nr_driver = InitNornir(inventory=inventory, logging=self.logging_file, runner=runner)
        # Put in nornir config file
        # nr_driver = InitNornir(config_file=self.config_file, logging=self.logging_file)
        if self.username or self.password is not None:
            # Put in nornir cli username
            nr_driver.inventory.defaults.username = self.username
            # Put in nornir cli password
            nr_driver.inventory.defaults.password = self.password

        # Change default connection timers
        nr_driver.inventory.defaults.connection_options["napalm"] = ConnectionOptions(
            extras={"optional_args": {"conn_timeout": self.conn_timeout}}
        )
        return nr_driver
