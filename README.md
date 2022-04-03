[![Python 3.6](https://img.shields.io/badge/python-3.6-blue.svg)](https://www.python.org/downloads/release/python-360/)
[![Python 3.7](https://img.shields.io/badge/python-3.7-blue.svg)](https://www.python.org/downloads/release/python-370/)
[![Python 3.8](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/downloads/release/python-380/)
[![Python 3.9](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/downloads/release/python-390/)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)

# Network Automated BackUp System with Nornir, NetBox

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
* Flask

### Environment
* NetBox >= 3.0
### Device vendors
* Cisco
* Huawei
* Eltex
* If you need another device, then install an additional plugin for NAPALM

### Screenshots
![Screenshot of Search page](screenshots/search_page.png "Search page")
![Screenshot of Diff page](screenshots/diff_page.png "Diff page")
![Screenshot of Diff page context compare](screenshots/diff_page_context_compare.png "Diff page context compare")

# Installing

## Ubuntu 18.04 & 20.04
```
sudo apt-get update && sudo apt-get install python3-venv
```

## Clone repo and install dependencies
* download and setup of virtual environment
```
cd /opt
git clone https://github.com/Sivolen/NABS
cd NABS
python3 -m venv venv
. venv/bin/activate
pip3 install -r requirements.txt || pip install -r requirements.txt
```
# init DB
```
/opt/venv/bin/python3 -m flask db init
/opt/venv/bin/python3 -m flask db migrate
/opt/venv/bin/python3 -m flask db upgrade
```
# Running the web server
```
sudo apt-get -y install nginx
. venv/bin/activate
pip install gunicorn supervisor
# For test start
gunicorn -b localhost:8000 -w 4 app:app

cp /opt/NABS/supervisor/nabs.conf /etc/supervisor/conf.d/nabs.conf
sudo supervisorctl reload
```
# Configure Nginx
```
# Create dir for ssl certificate
mkdir certs
# Create ssl certificate
openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
  -keyout certs/key.pem -out certs/cert.pem
 
sudo rm /etc/nginx/sites-enabled/default
sudo cp /opt/NABS/supervisor/nabs /etc/nginx/available/nabs
sudo ln -s /etc/nginx/sites-available/nabs /etc/nginx/sites-enabled/nabs
sudo systemctl restart nginx
```
# Running the backup script
```
5 9-19 * * * /opt/NABS/venv/bin/python3 /opt/NABS/run_backup.py >/dev/null 2>&1
5 9-19 * * * /opt/NABS/venv/bin/python3 /opt/NABS/get_device_environment.py >/dev/null 2>&1

```

## Setup
Copy the [config_example.py](config_example.py) sample settings file to `config.py`.<br/>
Copy the [config_example.yaml](config_example.yaml) sample settings file to `config.yaml`.<br/>
If you are not using NetBox, then edit the [config_example.yaml](config_example.yaml) according to the [documentation](https://nornir.readthedocs.io/en/latest/tutorial/inventory.html). </br>
All options are described in the example file.

## Thanks
Nornir and nornir_netbox teams

