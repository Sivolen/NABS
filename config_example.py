### SSH Username & password ###
username = None
password = None
### SSH connection timeout
conn_timeout = 10
### Token from flask SECRET_KEY ###
TOKEN = ""
###
config_file = None
logging_file = None
### LDAP Settings ###
# If you need ldap (AD) login
AD_USE_SSL = False
AD_PORT = 389
AD_ADDRESS = ""
AD_SEARCH_TREE = ""
# If you have a problem with changing only the clock period in your configs, enable fix_clock_period
fix_clock_period = True
# Sometimes cisco configuration has two line break characters, this option replaces such characters with single ones
fix_dubl_line_feed = True
fix_platform_list = ("ios",)
### Web App mode ###
# [ProductionConfig, DevelopmentConfig, TestingConfig]
release_options = "ProductionConfig"
### DATABASE Parameters ###
DBHost = "localhost"
DBName = "nabs"
DBUser = "nabs"
DBPassword = "nabs"
# This variable contains the number of processes involved when running a single poll of a device (check device).
proccesor_pool = 4
# device drivers
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
