from app.models import GroupPermition, Devices, AssociatingDevice
from app import db, logger
from sqlalchemy.sql import text


def create_associate_device_group(user_group_id: int, device_id: int):
    """
    This function create a new permission to the database.
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
    This function is needed to delete user role from db
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


def update_associate_device_group(
    associate_id: int, device_id: int, user_group_id: int
) -> bool:
    """
    This function update an associate to the DB
    parm:
        associate_id: int
        device_id: int
        user_group_id: int
    return:
        bool
    """
    try:
        # Getting device data from db
        data = db.session.query(GroupPermition).filter_by(id=int(associate_id)).first()
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
    Get all Roles
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


# def get_associate_user_group(user_id: int) -> list:
#     """
#     Get all Roles
#     """
#     # associate_data = GropupPermition.query.order_by(GropupPermition.id)
#     if isinstance(user_id, int) and user_id is not None:
#         try:
#             slq_request = text(
#                 "SELECT Group_Permition.id, "
#                 "Group_Permition.device_id, "
#                 "Group_Permition.group_id, "
#                 "Group_Permition.user_id,"
#                 "(SELECT Devices.device_hostname FROM Devices WHERE Devices.id = Group_Permition.device_id) "
#                 "as device_hostname, "
#                 "(SELECT Users.email FROM Users WHERE Users.id = Group_Permition.user_id) "
#                 "as user_email, "
#                 "(SELECT User_Group.user_group_name FROM User_Group "
#                 "WHERE User_Group.id = Group_Permition.group_id) "
#                 "as group_name "
#                 "FROM Group_Permition "
#                 "LEFT JOIN Devices "
#                 "ON devices.id = group_permition.device_id "
#                 "LEFT JOIN Users "
#                 "ON users.id = group_permition.group_id "
#                 "LEFT JOIN Devices_Group "
#                 "ON devices_group.id = group_permition.group_id "
#                 "WHERE Group_Permition.user_id = :user_id "
#                 "GROUP BY Group_Permition.id "
#                 # "ORDER BY last_config_timestamp DESC "
#             )
#             parameters = {"user_id": user_id}
#             associate_data = db.session.execute(slq_request, parameters).fetchall()
#             return [
#                 {
#                     "html_element_id": html_element_id,
#                     "associate_id": data.id,
#                     "device_id": data.device_id,
#                     "user_group_id": data.group_id,
#                     "user_id": data.user_id,
#                     "device_hostname": data.device_hostname,
#                     "user_email": data.user_email,
#                     "group_name": data.group_name,
#                 }
#                 for html_element_id, data in enumerate(associate_data, start=1)
#             ]
#         except Exception as get_sql_error:
#             # If an error occurs as a result of writing to the DB,
#             # then rollback the DB and write a message to the log
#             logger.info(f"getting associate error {get_sql_error}")
#             db.session.rollback()


def check_associate(user_id: int, device_id: int) -> int or None:
    return (
        GroupPermition.query.with_entities(GroupPermition.id)
        .filter_by(device_id=device_id, user_id=user_id)
        .first()
    )


# def create_associate_user_group_all(user_id: int, user_group_id: int) -> bool:
#     """
#     Create associations for the entire group
#     """
#     try:
#         devices = Devices.query.with_entities(Devices.id).filter_by(group_id=user_group_id)
#         for device in devices:
#             check = check_associate(user_id=user_id, device_id=device["id"])
#             if check is None:
#                 create_associate_user_group(
#                     user_group_id=user_group_id, user_id=user_id, device_id=device["id"]
#                 )
#         return True
#     except Exception as get_sql_error:
#         logger.info(f"Error creating association for entire group {get_sql_error}")


def get_users_group(user_id: int) -> list:
    group_lsit_db = GroupPermition.query.with_entities(
        GroupPermition.id,
        GroupPermition.user_group_id,
    ).filter_by(user_id=user_id)
    return [group["user_group_id"] for group in group_lsit_db]


def check_allowed_device(groups_id: list, device_id: int) -> bool:
    """
    This function checks in user groups whether the user is allowed to view this device
    """
    allowed_device = False
    for group in groups_id:
        device = (
            AssociatingDevice.query.with_entities(AssociatingDevice.device_id)
            .filter_by(user_group_id=group, device_id=device_id)
            .first()
        )
        if device is not None:
            allowed_device = True
        else:
            allowed_device = False
    return allowed_device


def get_associate_device_group(user_group_id: int) -> list:
    """
    Get all Roles
    """
    if isinstance(user_group_id, int) and user_group_id is not None:
        try:
            slq_request = text(
                "SELECT Associating_Device.id, "
                "Associating_Device.device_id, "
                "Associating_Device.user_group_id, "
                "(SELECT Devices.device_hostname FROM Devices WHERE Devices.id = Associating_Device.device_id) "
                "as device_hostname, "
                "(SELECT User_Group.user_group_name FROM User_Group "
                "WHERE User_Group.id = Associating_Device.user_group_id) "
                "as user_group_name "
                "FROM Associating_Device "
                "LEFT JOIN Devices "
                "ON devices.id = associating_device.device_id "
                "LEFT JOIN Devices_Group "
                "ON devices_group.id = associating_device.user_group_id "
                "WHERE Associating_Device.user_group_id = :user_group_id "
                "GROUP BY Associating_Device.id "
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
    This function create a new permission to the database.
    Need to parm:
    user_group_id: int
    user_id: int
    return:
        Bool
    """
    try:
        associate_data = GroupPermition(
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
    This function is needed to delete user role from db
    Parm:
        id: int
    return:
        bool
    """
    try:
        GroupPermition.query.filter_by(id=int(associate_id)).delete()
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
    This function return all device groups
    """

    if isinstance(user_id, int) and user_id is not None:
        try:
            slq_request = text(
                "SELECT Group_Permition.id, "
                "Group_Permition.user_group_id, "
                "Group_Permition.user_id, "
                "User_Group.user_group_name "
                "FROM Group_Permition "
                "LEFT JOIN User_Group ON User_Group.id = group_permition.user_group_id "
                "LEFT JOIN associating_device ON associating_device.user_group_id = group_permition.user_group_id "
                "WHERE Group_Permition.user_id = :user_id "
                "GROUP BY Group_Permition.id, User_Group.user_group_name"
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


def get_associate_group_device(user_id: int) -> list:
    """
    This function return all device groups
    """

    if isinstance(user_id, int) and user_id is not None:
        try:
            slq_request = text(
                "SELECT Group_Permition.id, "
                "Group_Permition.user_group_id, "
                "Group_Permition.user_id, "
                "User_Group.user_group_name "
                "FROM Group_Permition "
                "LEFT JOIN User_Group ON User_Group.id = group_permition.user_group_id "
                "LEFT JOIN associating_device ON associating_device.user_group_id = group_permition.user_group_id "
                "WHERE Group_Permition.user_id = :user_id "
                "GROUP BY Group_Permition.id, User_Group.user_group_name"
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
