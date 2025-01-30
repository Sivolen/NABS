# from sqlalchemy import text
from sqlalchemy.sql import text
from app.models import Devices
from app import db, logger


def get_device_id_by_hostname(hostname: str) -> dict:
    """
    This function return device id
    """
    """
     The function gets env for all devices to which the user has access from the database
     return:
     Devices env dict
     Get all Roles
     """
    if not isinstance(hostname, str) and hostname is None:
        return logger.info(
            f"Get devices id for {hostname} error, hostname mast be a string"
        )
    try:
        slq_request = text(
            """
            select id, 
            device_ip 
            from devices 
            where device_hostname = :device_hostname
            """
        )
        parameters = {"device_hostname": hostname}
        devices_data = db.session.execute(slq_request, parameters).fetchall()
        return {"device_id": devices_data[0][0], "device_ip": devices_data[0][1]}

    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"getting associate error {get_sql_error}")


def add_device(
    group_id: int,
    hostname: str,
    ipaddress: str,
    connection_driver: str,
    ssh_port: int,
    credentials_id: int,
    is_enabled: bool,
) -> bool:
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
            group_id=group_id,
            device_hostname=hostname,
            device_ip=ipaddress,
            connection_driver=connection_driver,
            ssh_port=ssh_port,
            credentials_id=credentials_id,
            is_enabled=is_enabled,
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


def update_device_credentials(
    device_id: int,
    credentials_id: int,
) -> bool:
    """
    This function is needed to update device param on db
    Parm:
        device_id: int
        credentials_id: int
    return:
        bool
    """
    try:
        if not isinstance(device_id, int) or device_id is None:
            logger.info(
                f"Update device credentials {device_id} error, device id must be an integer"
            )
            return False

        if not isinstance(credentials_id, int) or credentials_id is None:
            logger.info(
                f"Update device credentials {device_id} error, credentials id is must be an integer"
            )
            return False
        device_data = db.session.query(Devices).filter_by(id=int(device_id)).first()
        if device_data.credentials_id != credentials_id:
            device_data.credentials_id = credentials_id

        # Apply changing
        db.session.commit()
        return True
    except Exception as update_db_error:
        db.session.rollback()
        logger.info(f"Update device {device_id} error {update_db_error}")
        return False


def get_allowed_devices_by_right(user_id: int) -> list:
    """
    The function gets env for all devices to which the user has access from the database
    return:
    Devices env dict
    Get all Roles
    """
    if not isinstance(user_id, int) and user_id is None:
        return logger.info(f"Get devices for {user_id} error, user id must be a string")
    try:
        slq_request = text(
            """
            select Devices.id,  
            Devices.device_ip, 
            Devices.device_hostname, 
            Devices.credentials_id 
            from Associating_Device 
            left join Devices on Devices.id = Associating_Device.device_id  
            left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id 
            where group_permission.user_id = :user_id group by Devices.id
            """
        )
        parameters = {"user_id": user_id}
        devices_data = db.session.execute(slq_request, parameters).fetchall()
        return [
            {
                "html_element_id": html_element_id,
                "device_id": device[0],
                "device_ip": device[1],
                "device_hostname": device[2],
                "credentials_id": device[3],
            }
            for html_element_id, device in enumerate(devices_data, start=1)
        ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"getting associate error {get_sql_error}")


def get_devices_for_logs() -> list:
    """
    The function gets env for all devices to which the user has access from the database
    return:
    Devices env dict
    Get all Roles
    """
    try:
        slq_request = text(
            """
            select id,
            device_ip
            from devices
            """
        )
        devices_data = db.session.execute(slq_request).fetchall()
        return [
            {
                "device_id": device["id"],
                "device_ip": device["device_ip"],
            }
            for device in devices_data
        ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"getting associate error {get_sql_error}")


def get_devices_by_rights(user_id: int) -> list:
    """
    The function gets env for all devices to which the user has access from the database
    return:
    Devices env dict
    Get all Roles
    """
    if not isinstance(user_id, int) or user_id is None:
        return logger.info(
            f"Get devices data for {user_id} error, user id must be an integer"
        )
    try:
        slq_request = text(
            "select Devices.id, "
            "Devices.device_ip, "
            "Devices.device_hostname, "
            "Devices.device_vendor, "
            "Devices.device_model, "
            "Devices.connection_status, "
            "Devices.connection_driver, "
            "Devices.timestamp,"
            "count(Configs.device_id) as check_previous_config, "
            "(SELECT Devices_Group.group_name FROM Devices_Group WHERE Devices_Group.id = Devices.group_id) as device_group, "
            "(SELECT Configs.timestamp FROM Configs WHERE Configs.device_id = Devices.id ORDER BY Configs.id DESC LIMIT 1) as last_config_timestamp "
            "from Associating_Device left join Devices on Devices.id = Associating_Device.device_id "
            "left join Configs on Devices.id = Configs.device_id "
            "left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id "
            "where group_permission.user_id = :user_id group by Devices.id ORDER BY last_config_timestamp DESC"
        )
        parameters = {"user_id": user_id}
        devices_data = db.session.execute(slq_request, parameters).fetchall()
        return [
            {
                "html_element_id": html_element_id,
                "group_name": device[9],
                "device_id": device[0],
                "device_ip": device[1],
                "hostname": device[2],
                "vendor": device[3],
                "model": device[4],
                "connection_status": device[5],
                "connection_driver": device[6],
                "timestamp": device[7],
                "check_previous_config": (
                    True if device[8] is not None and int(device[8]) > 1 else False
                ),
                "last_config_timestamp": device[10] if device[10] is not None else None,
            }
            for html_element_id, device in enumerate(devices_data, start=1)
        ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"getting associate error {get_sql_error}")


def get_device_setting(device_id: int) -> dict:
    """
    This function needs to be get device data form db
    """
    if not isinstance(device_id, int) and device_id is None:
        return logger.info(
            f"Get device setting for {device_id} error, device id must be an integer"
        )
    try:
        slq_request = text(
            "select "
            "devices_group.id as device_group_id, "
            "devices_group.group_name as device_group, "
            "devices.device_ip as device_ip, "
            "devices.device_hostname as device_hostname, "
            "devices.connection_driver as connection_driver, "
            "devices.ssh_port as ssh_port, "
            "devices.credentials_id as credentials_id, "
            "devices.is_enabled as is_enabled "
            "from devices "
            "left join devices_group on devices_group.id = devices.group_id "
            "where devices.id = :device_id"
        )
        parameters = {"device_id": device_id}
        device_data = db.session.execute(slq_request, parameters).fetchall()
        return {
            "device_group_id": device_data[0][0],
            "device_group": (
                device_data[0][1] if device_data[0][0] is not None else "none"
            ),
            "device_ip": device_data[0][2],
            "device_hostname": device_data[0][3],
            "connection_driver": device_data[0][4],
            "ssh_port": device_data[0][5],
            "credentials_id": device_data[0][6],
            "is_enabled": device_data[0][7],
            "user_group": get_device_user_group(device_id=int(device_id)),
        }
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"getting associate error {get_sql_error}")


def get_device_user_group(device_id: int) -> list:
    if not isinstance(device_id, int) and device_id is None:
        return logger.info(
            f"Get device user group for {device_id} error, device id must be an integer"
        )
    try:
        slq_request = text(
            "select user_group.id as user_group_id, user_group.user_group_name from"
            " user_group left join associating_device on"
            " associating_device.user_group_id = user_group.id where"
            " associating_device.device_id = :device_id "
        )

        parameters = {"device_id": device_id}
        user_groups = db.session.execute(slq_request, parameters).fetchall()
        return [user_group[1] for user_group in user_groups]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"getting associate error {get_sql_error}")


# The function gets env for all devices from database
def get_devices_env() -> list:
    """
    The function gets env for all devices from database
    works with only system admin users
    return:
    Devices env dict
    """
    data = db.session.execute(
        text(
            "SELECT Devices_group.group_name AS device_group, "
            "Devices.id, "
            "Devices.device_ip, Devices.device_hostname, "
            "Devices.device_vendor, "
            "Devices.device_model, "
            "Devices.connection_status, "
            "Devices.connection_driver, "
            "Devices.timestamp, "
            "count(Configs.device_id) as check_previous_config, "
            "(SELECT Configs.timestamp FROM Configs WHERE Configs.device_id = Devices.id ORDER BY Configs.id DESC LIMIT 1) as last_config_timestamp "
            "FROM Devices LEFT JOIN "
            "Configs ON configs.device_id = devices.id LEFT JOIN Devices_Group ON "
            "devices_group.id = devices.group_id GROUP BY Devices.id, "
            "Devices_group.group_name ORDER BY last_config_timestamp DESC"
        )
    )
    # for i in data:
    #     print(i._asdict()["device_hostname"])
    return [
        {
            "html_element_id": html_element_id,
            "group_name": device[0],
            "device_id": device[1],
            "device_ip": device[2],
            "hostname": device[3],
            "vendor": device[4],
            "model": device[5],
            "connection_status": device[6],
            "connection_driver": device[7],
            "timestamp": device[8],
            "check_previous_config": (
                True if device[9] is not None and int(device[9]) > 1 else False
            ),
            "last_config_timestamp": device[10] if device[10] is not None else None,
        }
        for html_element_id, device in enumerate(data, start=1)
    ]


def get_device_id(ipaddress: str) -> list:
    """
    This function return device id
    """
    return (
        Devices.query.with_entities(Devices.id).filter_by(device_ip=ipaddress).first()
    )


def update_driver_switch_status(switch_status: bool, device_id: int):
    """
    This function switching device custom driver switch
    parm:
        switch_status: bool
        device_id: int
    return:
        bool
    """
    if not isinstance(device_id, int) or device_id is None:
        logger.info(f"Update driver switch error, device_id must be an integer")
        return None
    if not isinstance(switch_status, int) or switch_status is None:
        logger.info(f"Update driver switch error, switch_status must be an Boolean")
        return None
    try:
        # Getting device data from db
        driver_data = db.session.query(Devices).filter_by(id=int(device_id)).first()
        driver_data.custom_drivers_switch = switch_status
        # Apply changing
        db.session.commit()
        return True

    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update driver error {update_sql_error}")
        db.session.rollback()
        return False


def get_driver_switch_status(device_id: int) -> bool:
    """
    This function return device driver switch status
    """
    return (
        Devices.query.with_entities(Devices.custom_drivers_switch)
        .filter_by(id=device_id)
        .first()[0]
    )


def get_custom_driver_id(device_id: int) -> int:
    """
    This function return connection_driver if driver switch status is True
    """
    return (
        Devices.query.with_entities(Devices.connection_driver)
        .filter_by(id=device_id)
        .first()[0]
    )


def get_device_is_enabled(device_id: int) -> bool:
    """
    This function return is_enabled status
    """
    return (
        Devices.query.with_entities(Devices.is_enabled)
        .filter_by(id=device_id)
        .first()[0]
    )
