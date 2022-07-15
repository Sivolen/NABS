### SSH Username & password ###
USERNAME = ""
PASS = ""
### SSH connection timeout
conn_timeout = 10
### Token from flask SECRET_KEY ###
TOKEN = ""
###
config_file = None
logging_file = None
### Activate local login ###
local_login = True
### LDAP Settings ###
# If you need ldap (AD) login, you should change local_login to False
AD_ADDRESS = ""
AD_SEARCH_TREE = ""
# If you have a problem with changing only the clock period in your configs, enable fix_clock_period
fix_clock_period = True
### Web App mode ###
test_env_release = "ProductionConfig"
### DATABASE Parameters ###
DBHost = "localhost"
DBName = "nabs"
DBUser = "nabs"
DBPassword = "nabs"
