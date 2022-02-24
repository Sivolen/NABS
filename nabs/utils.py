from nabs.models import Configs
from nabs import db


# The function gets the latest configuration file from the database for the provided device
def get_last_config_for_device(ipaddress: str) -> dict or None:
    """
    Need to parm:
    Ipaddress
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
        return {"last_config": db_last_config, "timestamp": db_last_timestamp}
    except:
        # If configuration not found return None
        return None


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_device(ipaddress: str) -> list or None:
    """
    Need to parm:
    Ipaddress
    """
    try:
        # Gets all timestamp from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress
        )
        return [db_timestamp.timestamp for db_timestamp in data[1:]]
    except:
        # If timestamp not found return None
        return None


# This function gets the previous config for this device from the DB
def get_previous_config(ipaddress: str, db_timestamp: str) -> str or None:
    """
    Need to parm:
    Ipaddress and timestamp
    """
    try:
        # Get configurations from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress, timestamp=db_timestamp
        )
        # The database returns a list, we get text data from it and return it from the function
        return data[0].device_config
    except:
        # If config not found return None
        return None


# This function writes a new configuration file to the DB
def write_cfg_on_db(ipaddress: str, config: str) -> None:
    """
    Need to parm:
    Ipaddress and config, timestamp generated automatically
    """
    # We form a request to the database and pass the IP address and device configuration
    config = Configs(device_ip=ipaddress, device_config=config)
    try:
        # Sending data in BD
        db.session.add(config)
        # Committing changes
        db.session.commit()
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        print(write_sql_error)
        db.session.rollback()
