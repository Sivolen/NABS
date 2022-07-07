import re
from app.models import Configs, Devices
from app import db


# Checking ipaddresses
def check_ip(ipaddress: int or str) -> bool:
    pattern = (
        r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1"
        "[0-9]"
        "{2}|2[0-4]["
        "0-9"
        "]|25[0-5])$"
    )
    return True if re.findall(pattern, ipaddress) else False


# The function is needed to check if the device is in database
def get_exist_device_on_db(ipaddress: str) -> bool:
    """
    The function is needed to check if the device is in database
    """
    try:
        # Get last configurations from DB
        data = (
            Devices.query.order_by(Devices.timestamp.desc())
            .filter_by(device_ip=ipaddress)
            .first()
        )
        if data:
            return True
        else:
            return False
    except:
        return False


# The function gets env for all devices from database
def get_devices_env() -> dict:
    """
    The function gets env for all devices from database
    return:
    Devices env dict
    """
    # Create dict for device environment data
    devices_env_dict = {}
    # Gets devices ip from database
    data = Devices.query.order_by(Devices.device_ip.desc())
    # Create list for device ip addresses
    ip_list = [ip.device_ip for ip in data]
    # Create a tuple for unique ip addresses
    ip_list = sorted(tuple(set(ip_list)))

    # This variable need to create html element id for accordion
    for html_element_id, ip in enumerate(ip_list, start=1):
        db_data = get_last_env_for_device_from_db(ip)
        # Checking if the previous configuration exists to enable/disable
        # the "Compare configuration" button on the device page
        check_previous_config = check_if_previous_configuration_exists(ipaddress=ip)
        # Getting last config timestamp for device page
        if get_last_config_for_device(ipaddress=ip) is None:
            last_config_timestamp = "No backup yet"
        else:
            last_config_timestamp = get_last_config_for_device(ipaddress=ip)[
                "timestamp"
            ]
        # If the latest configuration does not exist, return "No backup yet"
        if last_config_timestamp is None:
            last_config_timestamp = "No backup yet"
        # Update device dict
        devices_env_dict.update(
            {
                ip: {
                    "id": db_data["id"],
                    "html_element_id": f"{html_element_id}",
                    "hostname": db_data["hostname"],
                    "vendor": db_data["vendor"],
                    "model": db_data["model"],
                    "os_version": db_data["os_version"],
                    "sn": db_data["sn"],
                    "uptime": db_data["uptime"],
                    "connection_status": db_data["connection_status"],
                    "connection_driver": db_data["connection_driver"],
                    "timestamp": db_data["timestamp"],
                    "check_previous_config": check_previous_config,
                    "last_config_timestamp": last_config_timestamp,
                }
            }
        )
    return devices_env_dict


# The function gets the latest env from the database for the provided device
def get_last_env_for_device_from_db(ipaddress: str) -> dict or None:
    """
    Need to parm:
    Ipaddress
    return:
    device env dict or None
    """
    try:
        # Get last configurations from DB
        data = (
            Devices.query.order_by(Devices.timestamp.desc())
            .filter_by(device_ip=ipaddress)
            .first()
        )
        return {
            "id": data.id,
            "ipaddress": data.device_ip,
            "hostname": data.device_hostname,
            "vendor": data.device_vendor,
            "model": data.device_model,
            "os_version": data.device_os_version,
            "sn": data.device_sn,
            "connection_status": data.connection_status,
            "connection_driver": data.connection_driver,
            "uptime": data.device_uptime,
            "timestamp": data.timestamp,
        }
    except Exception as db_error:
        print(db_error)
        # If env not found return None
        return None


# This function update a device environment file to the DB
def update_device_env_on_db(
    ipaddress: str,
    hostname: str,
    vendor: str,
    model: str,
    os_version: str,
    sn: str,
    uptime: str,
    connection_status: str,
    connection_driver: str,
    timestamp: str,
) -> None:
    """
    This function update a device environment file to the DB
    parm:
        ipaddress: str
        hostname: str
        vendor: str
        model: str
        os_version: str
        sn: str
        uptime: str
        timestamp: str
    return:
        None
    """
    try:
        # Getting device data from db
        data = db.session.query(Devices).filter_by(device_ip=ipaddress).first()
        # If device hostname changed overwrite data on db
        if data.device_hostname != hostname:
            data.device_hostname = hostname
        # If device vendor name changed overwrite data on db
        if data.device_vendor != vendor:
            data.device_vendor = vendor
        # If device model changed overwrite data on db
        if data.device_model != model:
            data.device_model = model
        # If device os version changed overwrite data on db
        if data.device_os_version != os_version:
            data.device_os_version = os_version
        # If device serial number changed overwrite data on db
        if data.device_sn != sn:
            data.device_sn = sn
        if data.connection_status != connection_status:
            data.connection_status = connection_status
        if data.connection_driver != connection_driver:
            data.connection_driver = connection_driver
        # Overwrite device uptime on db
        data.device_uptime = uptime
        # Overwrite timestamp on db
        data.timestamp = timestamp
        # Apply changing
        db.session.commit()
        db.session.close()
    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        print(update_sql_error)
        db.session.rollback()


# This function update a device environment file to the DB
def update_device_status_on_db(
    ipaddress: str,
    connection_status: str,
    timestamp: str,
) -> None:
    """
    This function update a device environment file to the DB
    parm:
        ipaddress: str
        connection_status: str
        timestamp: str
    return:
        None
    """
    try:
        # Getting device data from db
        data = db.session.query(Devices).filter_by(device_ip=ipaddress).first()
        if data.connection_status != connection_status:
            data.connection_status = connection_status
        # Overwrite timestamp on db
        data.timestamp = timestamp
        # Apply changing
        db.session.commit()
        db.session.close()
    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        print(update_sql_error)
        db.session.rollback()


# This function writes a new device environment file to the DB if device is not exist
def write_device_env_on_db(
    ipaddress: str,
    hostname: str,
    vendor: str,
    model: str,
    os_version: str,
    sn: str,
    uptime: str,
    connection_status: str,
    connection_driver: str,
) -> None:
    """
    This function writes a new device environment file to the DB if device is not exist
    Need to parm:
        ipaddress: str
        hostname: str
        vendor: str
        model: str
        os_version: str
        sn: str
        uptime: str
    Ipaddress and config, timestamp generated automatically
    return:
        None
    """
    # We form a request to the database and pass the IP address and device environment
    device_env = Devices(
        device_ip=ipaddress,
        device_hostname=hostname,
        device_vendor=vendor,
        device_model=model,
        device_os_version=os_version,
        device_sn=sn,
        device_uptime=uptime,
        connection_status=connection_status,
        connection_driver=connection_driver,
    )
    try:
        # Sending data in BD
        db.session.add(device_env)
        # Committing changes
        db.session.commit()
        db.session.close()
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        print(write_sql_error)
        db.session.rollback()


# The function gets the latest configuration file from the database for the provided device
def get_last_config_for_device(ipaddress: str) -> dict or None:
    """
    Need to parm:
        Ipaddress: str
    return:
    Dict or None
    """
    try:
        # Get last configurations from DB
        data = (
            Configs.query.order_by(Configs.timestamp.desc())
            .filter_by(device_ip=ipaddress)
            .first()
        )
        # Variable for device configuration
        db_last_config = data.device_config
        # Variable to set the timestamp
        db_last_timestamp = data.timestamp
        db_last_id = data.id
        return {
            "id": db_last_id,
            "last_config": db_last_config,
            "timestamp": db_last_timestamp,
        }
    except:
        # If configuration not found return None
        return None


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_device(ipaddress: str) -> list or None:
    """
    Need to parm:
        Ipaddress: str
    return
        List or None
    """
    try:
        # Gets all timestamp from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress
        )
        # Return list minus last config timestamp
        return [db_timestamp.timestamp for db_timestamp in data[1:]]
    except:
        # If timestamp not found return None
        return None


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_config_page(ipaddress: str) -> list or None:
    """
    Need to parm:
        Ipaddress: str
    return
        List or None
    """
    try:
        # Gets all timestamp from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress
        )
        # Return list minus last config timestamp
        return [db_timestamp.timestamp for db_timestamp in data]
    except:
        # If timestamp not found return None
        return None


# This function gets the previous config for this device from the DB
def get_previous_config(ipaddress: str, db_timestamp: str) -> dict or None:
    """
    Need to parm:
        Ipaddress
        timestamp
    return
        str or None
    """
    try:
        # Get configurations from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress, timestamp=db_timestamp
        )
        # The database returns a list, we get text data from it and return it from the function
        return {
            "id": data[0].id,
            "device_config": data[0].device_config,
            "timestamp": data[0].timestamp,
        }
    except:
        # If config not found return None
        return None


# This function is needed to check if there are previous configuration versions
# for the device in the database check
def check_if_previous_configuration_exists(ipaddress: str) -> bool:
    """
    # This function is needed to check
    if there are previous configuration versions
    for the device in the database check
    Parm:
        ipaddress: str
    return:
        bool
    """
    # Get configurations from DB
    data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
        device_ip=ipaddress
    )
    # Len configs
    configs_list = [ip.device_ip for ip in data]
    return True if len(configs_list) > 1 else False


# This function writes a new configuration file to the DB
def write_cfg_on_db(ipaddress: str, config: str) -> None:
    """
    Need to parm:
        Ipaddress and config, timestamp generated automatically
    return
        None
    """
    # We form a request to the database and pass the IP address and device configuration
    config = Configs(device_ip=ipaddress, device_config=config)
    try:
        # Sending data in BD
        db.session.add(config)
        # Committing changes
        db.session.commit()
        db.session.close()
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        print(write_sql_error)
        db.session.rollback()


def add_device_on_db(hostname: str, ipaddress: str, connection_driver: str) -> bool:
    """
    This function is needed to add device param on db
    Parm:
        hostname: str
        ipaddress: str
        connection_driver: str
    return:
        bool
    """
    try:
        data = Devices(
            device_hostname=hostname,
            device_ip=ipaddress,
            connection_driver=connection_driver,
        )
        # Sending data in BD
        db.session.add(data)
        # Apply changing
        db.session.commit()
        return True
    except Exception as update_db_error:
        db.session.rollback()
        print(update_db_error)
        return False


def update_device_on_db(
    hostname: str, old_ipaddress: str, new_ipaddress, connection_driver: str
) -> bool:
    """
    This function is needed to update device param on db
    Parm:
        hostname: str
        ipaddress: str
        connection_driver: str
    return:
        bool
    """
    try:
        data = db.session.query(Devices).filter_by(device_ip=old_ipaddress).first()

        if data.device_hostname != hostname:
            data.device_hostname = hostname
        if data.device_ip != new_ipaddress:
            data.device_ip = new_ipaddress
        if data.connection_driver != connection_driver:
            data.connection_driver = connection_driver

        # Apply changing
        db.session.commit()
        return True
    except Exception as update_db_error:
        db.session.rollback()
        print(update_db_error)
        return False


def delete_device_from_db(ipaddress: str) -> bool:
    """
    This function is needed to delete device from db
    Parm:
        ipaddress: str
    return:
        bool
    """
    try:
        configs = Configs.query.filter_by(device_ip=ipaddress).first()
        if configs is not None:
            for config in configs:
                Configs.query.filter_by(ip=config.id).delete()
        Devices.query.filter_by(device_ip=ipaddress).delete()
        db.session.commit()
        return True
    except Exception as delete_device_error:
        db.session.rollback()
        print(delete_device_error)
        return False


def delete_config_from_db(config_id: str) -> bool:
    """
    This function is needed to delete device config from db
    Parm:
        id: str
    return:
        bool
    """
    try:
        Configs.query.filter_by(id=int(config_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_error:
        db.session.rollback()
        print(delete_device_error)
        return False
