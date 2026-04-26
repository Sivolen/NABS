### SSH Username & password  for netbox importer ###
username = None
password = None
### SSH connection timeout
conn_timeout = 10
### Token from flask SECRET_KEY ###
TOKEN = ""
###
config_file = None
logging_file = None
auth_methods = ["ldap", "local"]
### LDAP Settings ###
# If you need ldap (AD) login
AD_USE_SSL = False
AD_PORT = 389
AD_ADDRESS = ""
AD_SEARCH_TREE = ""
# If you have a problem with changing only the clock period in your configs, enable fix_clock_period
fix_clock_period = True
# Sometimes cisco configuration has two line break characters, this option replaces such characters with single ones
fix_double_line_feed = True
fix_platform_list = ("ios",)
### Web App mode ###
# [ProductionConfig, DevelopmentConfig, TestingConfig]
release_options = "ProductionConfig"
### DATABASE Parameters ###
DBHost = "localhost"
DBName = "nabs"
DBUser = "nabs"
DBPassword = "nabs"
DBPort = "5432"
# This variable contains the number of processes involved when running a single poll of a device (check device).
proccesor_pool = 4
# Clear configs patterns
enable_clearing = True
clear_patterns = [
    r"! No configuration change since last restart\s*",
    r"ntp\sclock-period\s[0-9]{1,30}\n",
]
# EMAIL Reports
SMTP_HOST = ""
SMTP_FROM = ""
SMTP_PORT = 25
SMTP_AUTH = False
SMTP_USER = ""
SMTP_PASSWORD = ""
EMAIL_DIFF_MAX_LINES = 50
NABS_BASE_URL = "https://your-nabs-domain.com"
# Cron TimeZone
SCHEDULER_TIMEZONE = "Asia/Sakhalin"
# Netmiko read timeout in seconds for sending commands (e.g., 'display current-configuration')
# Increase this value if you have large configurations or slow devices.
NETMIKO_READ_TIMEOUT = 60
# NAPALM device drivers
drivers = [
    {
        "name": "Cisco",
        "driver": "ios",
    },
    {
        "name": "Cisco nx",
        "driver": "nxos_ssh",
    },
    {
        "name": "Cisco sg",
        "driver": "sg350",
    },
    {
        "name": "Huawei sw",
        "driver": "huawei_vrp",
    },
    {
        "name": "Huawei ce",
        "driver": "ce",
    },
    {
        "name": "Eltex",
        "driver": "eltex",
    },
]
