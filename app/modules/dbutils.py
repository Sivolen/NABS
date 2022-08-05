from app.models import Configs, Devices
from app import db, logger


# The function is needed to check if the device is in database
def get_exist_device(device_id: int) -> bool:
    """
    The function is needed to check if the device is in database
    """
    try:
        # Get last configurations from DB
        data = (
            Devices.query.order_by(Devices.timestamp.desc())
            .filter_by(device_id=int(device_id))
            .first()
        )
        return True if data else False
    except:
        return False


# The function gets env for all devices from database
# def get_devices_env() -> dict:
#     """
#     The function gets env for all devices from database
#     return:
#     Devices env dict
#     """
#     # Create dict for device environment data
#     devices_env_dict = {}
#     # Gets devices ip from database
#     data = Devices.query.with_entities(Devices.device_ip)
#     # Create list for device ip addresses
#     ip_list = [ip.device_ip for ip in data]
#     # Create a tuple for unique ip addresses
#     ip_list = sorted(tuple(set(ip_list)))
#
#     # This variable need to create html element id for accordion
#     for html_element_id, ipaddress in enumerate(ip_list, start=1):
#         db_data = get_last_env_for_device(ipaddress=ipaddress)
#         # Checking if the previous configuration exists to enable/disable
#         # the "Compare configuration" button on the device page
#         check_previous_config = check_if_previous_configuration_exists(
#             ipaddress=ipaddress
#         )
#         # Getting last config timestamp for device page
#         last_config = check_last_config(ipaddress=ipaddress)
#         if last_config is None:
#             last_config_timestamp = "No backup yet"
#         else:
#             last_config_timestamp = last_config[
#                 "timestamp"
#             ]
#         # If the latest configuration does not exist, return "No backup yet"
#         if last_config_timestamp is None:
#             last_config_timestamp = "No backup yet"
#         # Update device dict
#         devices_env_dict.update(
#             {
#                 ipaddress: {
#                     "html_element_id": f"{html_element_id}",
#                     "id": db_data.id,
#                     "hostname": db_data.device_hostname,
#                     "vendor": db_data.device_vendor,
#                     "model": db_data.device_model,
#                     "os_version": db_data.device_os_version,
#                     "sn": db_data.device_sn,
#                     "uptime": db_data.device_uptime,
#                     "connection_status": db_data.connection_status,
#                     "connection_driver": db_data.connection_driver,
#                     "timestamp": db_data.timestamp,
#                     "check_previous_config": check_previous_config,
#                     "last_config_timestamp": last_config_timestamp,
#                 }
#             }
#         )
#     return devices_env_dict


# The function gets the latest env from the database for the provided device
def get_last_env_for_device(device_id: str) -> dict or None:
    """
    Need to parm:
    Ipaddress
    return:
    device env dict or None
    """
    try:
        # Get last device env from DB
        return (
            Devices.query.order_by(Devices.timestamp.desc())
            .filter_by(id=int(device_id))
            .first()
        )
    except Exception as db_error:
        logger.info(
            f"When getting data from the database about env reproduced error {db_error}"
        )
        # If env not found return None
        return None


# This function update a device environment file to the DB
def update_device_env(
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
        logger.info(f"Update device error {update_sql_error}")
        db.session.rollback()


# This function update a device environment file to the DB
def update_device_status(
    device_id: int,
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
        data = db.session.query(Devices).filter_by(device_id=int(device_id)).first()
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
        logger.info(f"Update device status error {update_sql_error}")
        db.session.rollback()


# This function writes a new device environment file to the DB if device is not exist
def write_device_env(
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
        logger.info(f"Write device error {write_sql_error}")
        db.session.rollback()


# The function gets the latest configuration file from the database for the provided device
def get_last_config_for_device(device_id: int) -> dict or None:
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
            .filter_by(device_id=int(device_id))
            .first()
        )
        return {
            # Variable for device configuration
            "id": data.id,
            "last_config": data.device_config,
            # Variable for device configuration
            "timestamp": data.timestamp,
        }
    except:
        # If configuration not found return None
        return None


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_device(device_id: str) -> list or None:
    """
    Need to parm:
        Ipaddress: str
    return
        List or None
    """
    try:
        # Gets all timestamp from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_id=int(device_id)
        )
        # Return list minus last config timestamp
        return [db_timestamp.timestamp for db_timestamp in data[1:]]
    except:
        # If timestamp not found return None
        return None


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_config_page(device_id: str) -> list or None:
    """
    Need to parm:
        Ipaddress: str
    return
        List or None
    """
    try:
        # Gets all timestamp from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_id=int(device_id)
        )
        # Return list minus last config timestamp
        return [db_timestamp.timestamp for db_timestamp in data]
    except:
        # If timestamp not found return None
        return None


# This function gets the previous config for this device from the DB
def get_previous_config(device_id: str, db_timestamp: str) -> dict:
    """
    Need to parm:
        Ipaddress
        timestamp
    return
        str or None
    """
    # Get configurations from DB
    data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
        device_id=int(device_id), timestamp=db_timestamp
    )
    # The database returns a list, we get text data from it and return it from the function
    return {
        "id": data[0].id,
        "device_config": data[0].device_config,
        "timestamp": data[0].timestamp,
    }


# This function is needed to check if there are previous configuration versions
# for the device in the database check
def check_if_previous_configuration_exists(device_id: str) -> bool:
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
    data = Configs.query.with_entities(Configs.timestamp, Configs.device_ip).filter_by(device_id=int(device_id))
    # Len configs
    configs_list = [ip.device_ip for ip in data]
    return True if len(configs_list) > 1 else False


# This function writes a new configuration file to the DB
def write_config(ipaddress: str, config: str) -> None:
    """
    Need to parm:
        Ipaddress and config, timestamp generated automatically
    return
        None
    """
    # We form a request to the database and pass the IP address and device configuration
    device_id = get_device_id(ipaddress=ipaddress)
    if device_id is not None:
        config = Configs(device_ip=ipaddress, device_config=config, device_id=device_id["id"])
        try:
            # Sending data in BD
            db.session.add(config)
            # Committing changes
            db.session.commit()
            db.session.close()
        except Exception as write_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"Write cfg for {ipaddress} error {write_sql_error}")
            db.session.rollback()


def add_device(hostname: str, ipaddress: str, connection_driver: str) -> bool:
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
        logger.info(f"Add device {ipaddress} error {update_db_error}")
        return False


def update_device(
    hostname: str, device_id: str, new_ipaddress, connection_driver: str
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
        data = db.session.query(Devices).filter_by(id=int(device_id)).first()

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
        logger.info(f"Update device {device_id} error {update_db_error}")
        return False


def delete_device(device_id: str) -> bool:
    """
    This function is needed to delete device from db
    Parm:
        ipaddress: str
    return:
        bool
    """
    try:
        Configs.query.filter_by(device_id=int(device_id)).delete()
        # if configs is not None:
        #     for config in configs:
        #         Configs.query.filter_by(id=config.id).delete()
        Devices.query.filter_by(id=int(device_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_error:
        db.session.rollback()
        logger.info(f"Delete device {device_id} error {delete_device_error}")
        return False


def delete_config(config_id: str) -> bool:
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
        logger.info(f"Delete config id {config_id} error {delete_device_error}")
        return False


# The function gets env for all devices from database
def get_devices_env_new() -> dict:
    """
    The function gets env for all devices from database
    return:
    Devices env dict
    """
    # Create dict for device environment data
    devices_env_dict = {}
    # Gets devices ip from database
    data = Devices.query.with_entities(
        Devices.id,
        Devices.device_ip,
        Devices.device_hostname,
        Devices.device_vendor,
        Devices.device_model,
        Devices.device_os_version,
        Devices.device_sn,
        Devices.device_uptime,
        Devices.connection_status,
        Devices.connection_driver,
        Devices.timestamp,
    )

    # This variable need to create html element id for accordion
    for html_element_id, device in enumerate(data, start=1):

        # Checking if the previous configuration exists to enable/disable
        # the "Compare configuration" button on the device page
        check_previous_config = check_if_previous_configuration_exists(
            device_id=device.id
        )
        # # Getting last config timestamp for device page
        last_config_timestamp = check_last_config(device_id=device.id)

        # If the latest configuration does not exist, return "No backup yet"
        if last_config_timestamp is None:
            last_config_timestamp = "No backup yet"
        else:
            last_config_timestamp = last_config_timestamp["timestamp"]

        # Update device dict
        devices_env_dict.update(
            {
                device.id: {
                    "html_element_id": f"{html_element_id}",
                    "id": device.id,
                    "device_ip": device.device_ip,
                    "hostname": device.device_hostname,
                    "vendor": device.device_vendor,
                    "model": device.device_model,
                    "os_version": device.device_os_version,
                    "sn": device.device_sn,
                    "uptime": device.device_uptime,
                    "connection_status": device.connection_status,
                    "connection_driver": device.connection_driver,
                    "timestamp": device.timestamp,
                    "check_previous_config": check_previous_config,
                    "last_config_timestamp": last_config_timestamp,
                }
            }
        )
    return devices_env_dict


# The function gets the latest configuration file from the database for the provided device
def check_last_config(device_id: str) -> dict:
    """
    Need to parm:
        Ipaddress: str
    return:
    Dict or None
    """
    # Get last configurations from DB
    return Configs.query.with_entities(Configs.timestamp).filter_by(device_id=device_id).first()


def get_device_id(ipaddress: str) -> dict:
    """
    This function return device id
    """
    return Devices.query.with_entities(Devices.id).filter_by(device_ip=ipaddress).first()
