[![Python 3.6](https://img.shields.io/badge/python-3.6-blue.svg)](https://www.python.org/downloads/release/python-360/)
[![Python 3.7](https://img.shields.io/badge/python-3.7-blue.svg)](https://www.python.org/downloads/release/python-370/)
[![Python 3.8](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/downloads/release/python-380/)
[![Python 3.9](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/downloads/release/python-390/)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)

# Network Automated BackUp System with Nornir

This is a network device configuration backup tool.<br/>
You can import network device data from Netbox using Nornir with the nornir_netbox plugin or add devices manually.

**IMPORTANT: READ INSTRUCTIONS CAREFULLY BEFORE RUNNING THIS PROGRAM**


## Requirements
### Software
* python >= 3.8
* nornir
* napalm
* paramiko
* netmiko
* Flask

### Device vendors supported
* Cisco
* Huawei
* Eltex
* If you need another device, then install an additional plugin for NAPALM
```
. venv/bin/activate
pip3 install napalm-"drivername"
```

## Screenshots
![Screenshot of Search page](screenshots/devices_page.png "Devices page")
![Screenshot of Diff page](screenshots/diff_page.png "Diff page")
![Screenshot of Diff page context compare](screenshots/diff_page_context_compare.png "Diff page context compare")

# Installing

## Ubuntu 18.04 & 20.04
```
sudo apt update && sudo apt-get install python3-venv nginx supervisor postgresql
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

## init DB
```
sudo -u postgres psql
CREATE DATABASE NABS;
CREATE USER NABS WITH ENCRYPTED PASSWORD 'NABS';
GRANT ALL PRIVILEGES ON DATABASE NABS TO NABS;
QUIT;
```
```
. venv/bin/activate
flask db init
flask db migrate
flask db upgrade
```
## Setup configuration
Copy the [config_example.py](config_example.py) sample settings file to `config.py`.<br/>
Copy the [config_example.yaml](config_example.yaml) sample settings file to `config.yaml`.<br/>
If you are not using NetBox, then edit the [config_example.yaml](config_example.yaml) according to the [documentation](https://nornir.readthedocs.io/en/latest/tutorial/initializing_nornir.html) or add devices manually use "Add" on devices page. </br>
All options are described in the example file.

## Running the web server
```
. venv/bin/activate
pip install gunicorn supervisor
# For test start
gunicorn -b yourserveraddress:8000 -w 4 app:app

cp /opt/NABS/supervisor/nabs.conf /etc/supervisor/conf.d/nabs.conf
sudo supervisorctl reload
```
## Configure Nginx
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
## Running the backup script
```
0 */4 * * * /opt/NABS/venv/bin/python /opt/NABS/run_backup_sql.py >/dev/null 2>&1
```
## Run device import from netbox if you need it.
```
0 0 * * * /opt/NABS/venv/bin/python /opt/NABS/netbox_devices_importer.py >/dev/null 2>&1
```
# Update
* Update NABS and virtual environment
```
cd /opt/NABS
sudo git checkout origin/main
sudo git pull
. venv/bin/activate
pip3 install -r requirements.txt || pip install -r requirements.txt
```
* Update DB
```
. venv/bin/activate
flask db stamp head
flask db migrate
flask db upgrade
```
* Check [config_example.yaml](config_example.yaml) for new features and copy them into your config.py
* Reload supervisor
```
sudo service supervisor reload
```
# Thanks
Nornir and Napalm teams

