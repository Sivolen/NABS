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
NABS_DOMAIN = ".com"
# Cron TimeZone
SCHEDULER_TIMEZONE = "Asia/Sakhalin"
# Netmiko read timeout in seconds for sending commands (e.g., 'display current-configuration')
# Increase this value if you have large configurations or slow devices.
NETMIKO_READ_TIMEOUT = 120
# Sanity check for truncated/glitched config reads (e.g. some Eltex MES / Cisco SG350
# switches occasionally return just a couple of prompt lines instead of the full config
# when the CLI is slow/overloaded). Instead of a fixed line-count limit, the newly
# fetched config is compared to the LAST STORED config for the SAME device: if it's
# drastically shorter, it's treated as a glitch, not a real change.
enable_config_sanity_check = True
# Candidate config must have at least this fraction of the previous config's line count
config_sanity_min_ratio = 0.5
# Only apply the check if the previous config has at least this many lines
# (skips the check for devices that legitimately have a tiny config)
config_sanity_min_reference_lines = 20
# Number of extra retries if a suspicious/truncated config is detected
config_sanity_max_retries = 2
# Delay in seconds between retries (gives an overloaded device's CLI time to recover)
config_sanity_retry_delay = 5
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
