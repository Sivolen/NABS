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
SEND_REPORTS: bool = False
RECIPIENTS: list = []
SMTP_HOST = ""
SMTP_FROM = ""
SMTP_PORT = 25
SMTP_AUTH = False
SMTP_USER = ""
SMTP_PASSWORD = ""
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
netmiko_drivers = [
    "a10",
    "accedian",
    "adtran_os",
    "alcatel_aos",
    "alcatel_sros",
    "allied_telesis_awplus",
    "apresia_aeos",
    "arista_eos",
    "aruba_os",
    "aruba_osswitch",
    "aruba_procurve",
    "avaya_ers",
    "avaya_vsp",
    "broadcom_icos",
    "brocade_fastiron",
    "brocade_fos",
    "brocade_netiron",
    "brocade_nos",
    "brocade_vdx",
    "brocade_vyos",
    "calix_b6",
    "cdot_cros",
    "centec_os",
    "checkpoint_gaia",
    "ciena_saos",
    "cisco_asa",
    "cisco_ftd",
    "cisco_ios",
    "cisco_nxos",
    "cisco_s300",
    "cisco_tp",
    "cisco_wlc",
    "cisco_xe",
    "cisco_xr",
    "cloudgenix_ion",
    "coriant",
    "dell_dnos9",
    "dell_force10",
    "dell_isilon",
    "dell_os10",
    "dell_os6",
    "dell_os9",
    "dell_powerconnect",
    "dlink_ds",
    "eltex",
    "eltex_esr",
    "endace",
    "enterasys",
    "ericsson_ipos",
    "extreme",
    "extreme_ers",
    "extreme_exos",
    "extreme_netiron",
    "extreme_nos",
    "extreme_slx",
    "extreme_vdx",
    "extreme_vsp",
    "extreme_wing",
    "f5_linux",
    "f5_ltm",
    "f5_tmsh",
    "flexvnf",
    "fortinet",
    "generic",
    "generic_termserver",
    "hp_comware",
    "hp_procurve",
    "huawei",
    "huawei_olt",
    "huawei_smartax",
    "huawei_vrpv8",
    "ipinfusion_ocnos",
    "juniper",
    "juniper_junos",
    "juniper_screenos",
    "keymile",
    "keymile_nos",
    "linux",
    "mellanox",
    "mellanox_mlnxos",
    "mikrotik_routeros",
    "mikrotik_switchos",
    "mrv_lx",
    "mrv_optiswitch",
    "netapp_cdot",
    "netgear_prosafe",
    "netscaler",
    "nokia_sros",
    "oneaccess_oneos",
    "ovs_linux",
    "paloalto_panos",
    "pluribus",
    "quanta_mesh",
    "rad_etx",
    "raisecom_roap",
    "ruckus_fastiron",
    "ruijie_os",
    "sixwind_os",
    "sophos_sfos",
    "supermicro_smis",
    "tplink_jetstream",
    "ubiquiti_edge",
    "ubiquiti_edgerouter",
    "ubiquiti_edgeswitch",
    "ubiquiti_unifiswitch",
    "vyatta_vyos",
    "vyos",
    "watchguard_fireware",
    "yamaha",
    "zte_zxros",
]
