# NetBox-Network-Automation with Nornir

It is a tool for changing or backing up configuration on network devices.<br/>
It receives network data devices from Netbox using Nornir with
nornir_netbox plugin.

**IMPORTANT: READ INSTRUCTIONS CAREFULLY BEFORE RUNNING THIS PROGRAM**


## Requirements
### Software
* python >= 3.8
* nornir
* napalm
* napalm-ce
* napalm-eltex
* nornir-napalm
* nornir-netbox
* nornir-utils
* paramiko
* netmiko

### Environment
* NetBox >= 3.0
### Device vendors
* Cisco
* Huawei
* Eltex

# Installing

## Ubuntu 18.04 & 20.04
```
sudo apt-get update && sudo apt-get install python3-venv
```

## Clone repo and install dependencies
* download and setup of virtual environment
```
cd /opt
git clone https://github.com/Sivolen/netbox_config_backup.git
cd netbox_confog_backup-sync
python3 -m venv .venv
. .venv/bin/activate
pip3 install -r requirements.txt || pip install -r requirements.txt
```

# Running the script
```
Coming soon
```

## Setup
Copy the [config_example.py](config_example.py) sample settings file to `config.py`.<br/>
Copy the [config_example.yaml](config_example.yaml) sample settings file to `config.yaml`.<br/>
All options are described in the example file.

## Thanks
Nornir and nornir_netbox teams

