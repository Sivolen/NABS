from sqlalchemy import text

from app.models import Configs, Devices, AssociatingDevice
from app import db, logger
from app.modules.dbutils.db_devices import get_device_id


# The function gets the latest env from the database for the provided device
def get_last_env_for_device(device_id: str) -> dict:
    """
    Need to parm:
    Ipaddress
    return:
    device env dict or None
    """
    # Get last device env from DB
    data = (
        Devices.query.order_by(Devices.timestamp.desc())
        .filter_by(id=int(device_id))
        .first()
    )
    if data:
        return {
            "device_id": data.id,
            "device_ip": data.device_ip,
            "device_hostname": data.device_hostname,
        }


# This function update a device environment file to the DB
def update_device_env(
    device_id: int = None,
    hostname: str = None,
    vendor: str = None,
    model: str = None,
    connection_status: str = None,
    connection_driver: str = None,
    timestamp: str = None,
) -> None:
    """
    This function update a device environment file to the DB
    parm:
        device_id: int
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
        data = db.session.query(Devices).filter_by(id=device_id).first()
        # modify db data
        if hostname:
            data.device_hostname = hostname
        if vendor:
            data.device_vendor = vendor
        if model:
            data.device_model = model
        if connection_status:
            data.connection_status = connection_status
        if connection_driver:
            data.connection_driver = connection_driver
        if timestamp:
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
) -> bool:
    """
    This function update a device environment file to the DB
    parm:
        device_id: str
        connection_status: str
        timestamp: str
    return:
        None
    """
    try:
        # Getting device data from db
        data = db.session.query(Devices).filter_by(id=int(device_id)).first()
        if data.connection_status != connection_status:
            data.connection_status = connection_status
        # Overwrite timestamp on db
        data.timestamp = timestamp
        # Apply changing
        db.session.commit()
        db.session.close()
        return True
    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update device status error {update_sql_error}")
        db.session.rollback()
        return False


# The function gets the latest configuration file from the database for the provided device
def get_last_config_for_device(device_id: int) -> dict:
    """
    Need to parm:
        device_id: int
    return:
    Dict or None
    """
    # Get last configurations from DB
    data = (
        Configs.query.order_by(Configs.timestamp.desc())
        .filter_by(device_id=int(device_id))
        .first()
    )
    if data is not None:
        return {
            # Variable for device configuration
            "id": data.id,
            "last_config": data.device_config,
            # Variable for device configuration
            "timestamp": data.timestamp,
        }


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_device(device_id: int) -> list:
    """
    Need to parm:
        device_id: int
    return
        List or None
    """
    # Gets all timestamp from DB
    data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
        device_id=int(device_id)
    )
    # Return list minus last config timestamp
    return [db_timestamp.timestamp for db_timestamp in data[1:]]


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_config_page(device_id: int) -> list:
    """
    Need to parm:
        device_id: str
    return
        List or None
    """
    # Gets all timestamp from DB
    data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
        device_id=int(device_id)
    )
    # Return list minus last config timestamp
    return [db_timestamp.timestamp for db_timestamp in data]


# This function gets the previous config for this device from the DB
def get_previous_config(device_id: int, db_timestamp: str) -> dict:
    """
    Need to parm:
        device_id
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
def check_if_previous_configuration_exists(device_id: int) -> bool:
    """
    # This function is needed to check
    if there are previous configuration versions
    for the device in the database check
    Parm:
        device_id: str
    return:
        bool
    """
    # Get configurations from DB
    data = Configs.query.with_entities(Configs.timestamp, Configs.device_ip).filter_by(
        device_id=int(device_id)
    )
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
        config = Configs(
            device_ip=ipaddress, device_config=config, device_id=device_id[0]
        )
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


def update_device(
    hostname: str,
    device_id: int,
    new_ipaddress,
    connection_driver: str,
    group_id: int,
    ssh_port: int,
    credentials_id: int,
) -> bool:
    """
    This function is needed to update device param on db
    Parm:
        device_id: int
        hostname: str
        new_ipaddress: str
        connection_driver: str
        user_group_id: int,
        ssh_port: int,
        credentials_id: int,
    return:
        bool
    """
    try:
        device_data = db.session.query(Devices).filter_by(id=int(device_id)).first()
        if device_data.device_hostname != hostname:
            device_data.device_hostname = hostname
        if device_data.device_ip != new_ipaddress:
            device_data.device_ip = new_ipaddress
            configs_data = db.session.query(Configs).filter_by(device_id=int(device_id))
            for config_data in configs_data:
                config_data.device_ip = new_ipaddress
        if device_data.connection_driver != connection_driver:
            device_data.connection_driver = connection_driver

        if device_data.group_id != group_id:
            device_data.group_id = group_id

        if device_data.ssh_port != ssh_port:
            device_data.ssh_port = ssh_port

        if device_data.credentials_id != credentials_id:
            device_data.credentials_id = credentials_id

        # Apply changing
        db.session.commit()
        return True
    except Exception as update_db_error:
        db.session.rollback()
        logger.info(f"Update device {device_id} error {update_db_error}")
        return False


def delete_device(device_id: int) -> bool:
    """
    This function is needed to delete device from db
    Parm:
        device_id: int
    return:
        bool
    """
    try:
        Configs.query.filter_by(device_id=int(device_id)).delete()
        # if configs is not None:
        #     for config in configs:
        #         Configs.query.filter_by(id=config.id).delete()
        Devices.query.filter_by(id=int(device_id)).delete()
        AssociatingDevice.query.filter_by(device_id=int(device_id)).delete()
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
        logger.info(f"Delete config id {config_id} error {delete_device_error}")
        return False


# The function gets the latest configuration file from the database for the provided device
def check_last_config(device_id: int) -> dict:
    """
    Need to parm:
        device_id: int
    return:
    Dict or None
    """
    # Get last configurations from DB
    data = (
        Configs.query.order_by(Configs.timestamp.desc())
        .filter_by(device_id=int(device_id))
        .first()
    )
    return {"timestamp": data.timestamp}


def get_user_and_pass(device_id: int) -> dict:
    """
    This function return device id
    """
    if isinstance(device_id, int) and device_id is not None:
        try:
            slq_request = text(
                "SELECT "
                "credentials_username as username, "
                "credentials_password as password, "
                "ssh_port as port "
                "FROM Devices "
                "left join credentials on credentials.id = devices.Credentials_id "
                "where devices.id = :device_id "
            )
            parameters = {"device_id": device_id}
            db_data = db.session.execute(slq_request, parameters).fetchall()[0]
            return {
                "credentials_username": db_data[0],
                "credentials_password": db_data[1],
                "ssh_port": db_data[2],
            }

        except Exception as get_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"getting allowed credentials error {get_sql_error}")
