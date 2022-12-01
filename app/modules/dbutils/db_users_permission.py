from app.models import GroupPermission, Devices, AssociatingDevice
from app import db, logger
from sqlalchemy.sql import text


def create_associate_device_group(user_group_id: int, device_id: int):
    """
    This function associates a device with a user group
    Need to parm:
    user_group_id: int
    user_id: int
    return:
        Bool
    """
    try:
        associate_data = AssociatingDevice(
            user_group_id=user_group_id,
            device_id=device_id,
        )
        # Sending data in BD
        db.session.add(associate_data)
        # Committing changes
        db.session.commit()
        return True
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Creating associate error {write_sql_error}")
        db.session.rollback()
        return False


def delete_associate_device_group(associate_id: int):
    """
    This function is needed to remove a user group from the database.
    Parm:
        id: int
    return:
        bool
    """
    try:
        AssociatingDevice.query.filter_by(id=int(associate_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_group_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        db.session.rollback()
        logger.info(
            f"Delete user role id {associate_id} error {delete_device_group_error}"
        )
        return False


def delete_associate_by_device_id(device_id: int):
    """
    This function is needed to remove a device and user group association from the database.
    Parm:
        id: int
    return:
        bool
    """
    try:
        AssociatingDevice.query.filter_by(device_id=int(device_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_group_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        db.session.rollback()
        logger.info(
            f"Delete association on device id {device_id} error {delete_device_group_error}"
        )
        return False


def update_associate_device_group(
    associate_id: int, device_id: int, user_group_id: int
) -> bool:
    """
    This function updates the data about the bindings of the connection with the database
    parm:
        associate_id: int
        device_id: int
        user_group_id: int
    return:
        bool
    """
    try:
        # Getting device data from db
        data = db.session.query(GroupPermission).filter_by(id=int(associate_id)).first()
        if data.group_id != user_group_id:
            data.group_id = user_group_id
        if data.device_id != device_id:
            data.device_id = device_id
        # Apply changing
        db.session.commit()
        return True

    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update user role error {update_sql_error}")
        db.session.rollback()
        return False


def get_devices_list():
    """
    This function gets some data about all devices
    """
    devices = Devices.query.with_entities(
        Devices.id, Devices.device_hostname, Devices.device_ip
    )
    return [
        {
            "html_element_id": html_element_id,
            "device_id": device.id,
            "device_ip": device.device_ip,
            "device_hostname": device.device_hostname,
        }
        for html_element_id, device in enumerate(devices, start=1)
    ]


def get_users_group(user_id: int) -> list:
    """
    Get all groups the user is in for auth
    """
    group_list_db = GroupPermission.query.with_entities(
        GroupPermission.id,
        GroupPermission.user_group_id,
    ).filter_by(user_id=user_id)
    return [group["user_group_id"] for group in group_list_db]


def check_allowed_device(groups_id: list, device_id: int) -> bool:
    """
    This function checks in user groups whether the user is allowed to view this device
    """
    slq_request = text(
        "select "
        "associating_device.user_group_id "
        "FROM associating_device "
        "left join devices on devices.id = associating_device.device_id "
        "where device_id = :device_id "
    )
    parameters = {"device_id": device_id}
    devices = db.session.execute(slq_request, parameters).fetchall()
    for device in devices:
        if device[0] in groups_id:
            return True
    return False


def get_associate_device_group(user_group_id: int) -> list:
    """
    In this function, get all associated devices with a custom group
    """
    if isinstance(user_group_id, int) and user_group_id is not None:
        try:
            slq_request = text(
                "SELECT Associating_Device.id, "
                "Associating_Device.device_id, "
                "Associating_Device.user_group_id, "
                "Devices.device_hostname, "
                "Devices.device_ip, "
                "User_Group.user_group_name "
                "FROM Associating_Device "
                "LEFT JOIN Devices ON devices.id = associating_device.device_id "
                "LEFT JOIN Devices_Group ON devices_group.id = associating_device.user_group_id "
                "LEFT join User_Group ON User_Group.id = Associating_Device.user_group_id "
                "WHERE Associating_Device.user_group_id = :user_group_id "
                "GROUP BY Associating_Device.id, Devices.device_hostname, Devices.device_ip, User_Group.user_group_name"
            )
            parameters = {"user_group_id": user_group_id}
            associate_data = db.session.execute(slq_request, parameters).fetchall()
            return [
                {
                    "html_element_id": html_element_id,
                    "associate_id": data.id,
                    "device_id": data.device_id,
                    "user_group_id": data.user_group_id,
                    "device_hostname": data.device_hostname,
                    "device_ip": data.device_ip,
                    "user_group_name": data.user_group_name,
                }
                for html_element_id, data in enumerate(associate_data, start=1)
            ]
        except Exception as get_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"getting associate error {get_sql_error}")
            db.session.rollback()


def create_associate_user_group(user_group_id: int, user_id: int):
    """
    This function binds a user to a group.    Need to parm:
    user_group_id: int
    user_id: int
    return:
        Bool
    """
    try:
        associate_data = GroupPermission(
            user_group_id=user_group_id,
            user_id=user_id,
        )
        # Sending data in BD
        db.session.add(associate_data)
        # Committing changes
        db.session.commit()
        return True
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Creating associate error {write_sql_error}")
        db.session.rollback()
        return False


def delete_associate_user_group(associate_id: int):
    """
    This function unlinks a user from a group.    Parm:
        id: int
    return:
        bool
    """
    try:
        GroupPermission.query.filter_by(id=int(associate_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_group_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        db.session.rollback()
        logger.info(
            f"Delete user role id {associate_id} error {delete_device_group_error}"
        )
        return False


def get_associate_user_group(user_id: int) -> list:
    """
    This function returns all groups the user is associated with.
    """

    if isinstance(user_id, int) and user_id is not None:
        try:
            slq_request = text(
                "SELECT Group_Permission.id, "
                "Group_Permission.user_group_id, "
                "Group_Permission.user_id, "
                "User_Group.user_group_name "
                "FROM Group_Permission "
                "LEFT JOIN User_Group ON User_Group.id = Group_Permission.user_group_id "
                "LEFT JOIN associating_device ON associating_device.user_group_id = Group_Permission.user_group_id "
                "WHERE Group_Permission.user_id = :user_id "
                "GROUP BY Group_Permission.id, User_Group.user_group_name"
            )

            parameters = {"user_id": user_id}
            associate_data = db.session.execute(slq_request, parameters).fetchall()
            return [
                {
                    "html_element_id": html_element_id,
                    "group_permission_id": group.id,
                    "user_group_id": group.user_group_id,
                    "user_group_name": group.user_group_name,
                }
                for html_element_id, group in enumerate(associate_data, start=1)
            ]

        except Exception as get_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"getting associate error {get_sql_error}")
            db.session.rollback()
