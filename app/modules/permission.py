from app.models import UserRoles, GropupPermition, Devices
from app import db, logger
from sqlalchemy.sql import text


def check_user_role_if_exist(role_name: str) -> bool:
    db_data = (
        UserRoles.query.with_entities(UserRoles.role_name)
        .filter_by(role_name=role_name)
        .first()
    )
    if db_data is not None:
        return True if db_data[0] != role_name.lower() else False
    else:
        return True


def create_user_role(role_name: str):
    """
    This function create a new user role to the database.
    Need to parm:
    role_name: str
    return:
        Bool
    """
    if check_user_role_if_exist(role_name=role_name):
        role_name = UserRoles(
            role_name=role_name.lower(),
        )
        try:
            # Sending data in BD
            db.session.add(role_name)
            # Committing changes
            db.session.commit()
            return True
        except Exception as write_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"Creating role error {write_sql_error}")
            db.session.rollback()
            return False
    else:
        logger.info(f"Creating role error {role_name} is exist")
        return False


def delete_user_role(role_id: int):
    """
    This function is needed to delete user role from db
    Parm:
        id: int
    return:
        bool
    """
    try:
        UserRoles.query.filter_by(id=int(role_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_group_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        db.session.rollback()
        logger.info(f"Delete user role id {role_id} error {delete_device_group_error}")
        return False


def update_user_role(role_id: int, role_name: str) -> bool:
    """
    This function update a user role to the DB
    parm:
        group_id: int
        group_name: str
    return:
        bool
    """
    try:
        # Getting device data from db
        data = db.session.query(UserRoles).filter_by(id=int(role_id)).first()
        if data.role_name != role_name:
            data.role_name = role_name
        # Apply changing
        db.session.commit()
        return True

    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update user role error {update_sql_error}")
        db.session.rollback()
        return False


def create_associate_user_group(group_id: int, user_id: int, device_id: int):
    """
    This function create a new permission to the database.
    Need to parm:
    group_id: int
    user_id: int
    device_id: int
    return:
        Bool
    """
    try:
        associate_data = GropupPermition(
            group_id=group_id, user_id=user_id, device_id=device_id
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


def get_associate_user_group(user_id: int) -> list:
    """
    Get all Roles
    """
    # associate_data = GropupPermition.query.order_by(GropupPermition.id)
    if isinstance(user_id, int) and user_id is not None:
        try:
            slq_request = text(
                "SELECT Gropup_Permition.id, "
                "Gropup_Permition.device_id, "
                "Gropup_Permition.group_id, "
                "Gropup_Permition.user_id,"
                "(SELECT Devices.device_hostname FROM Devices WHERE Devices.id = Gropup_Permition.device_id) "
                "as device_hostname, "
                "(SELECT Users.email FROM Users WHERE Users.id = Gropup_Permition.user_id) "
                "as user_email, "
                "(SELECT Devices_Group.group_name FROM Devices_Group "
                "WHERE Devices_Group.id = Gropup_Permition.group_id) "
                "as group_name "
                "FROM Gropup_Permition "
                "LEFT JOIN Devices "
                "ON devices.id = gropup_permition.device_id "
                "LEFT JOIN Users "
                "ON users.id = gropup_permition.group_id "
                "LEFT JOIN Devices_Group "
                "ON devices_group.id = gropup_permition.group_id "
                "WHERE Gropup_Permition.user_id = :user_id "
                "GROUP BY Gropup_Permition.id "
                # "ORDER BY last_config_timestamp DESC "
            )
            parameters = {'user_id': user_id}
            associate_data = db.session.execute(slq_request, parameters).fetchall()
            return [
                {
                    "html_element_id": html_element_id,
                    "associate_id": data.id,
                    "device_id": data.device_id,
                    "group_id": data.group_id,
                    "user_id": data.user_id,
                    "device_hostname": data.device_hostname,
                    "user_email": data.user_email,
                    "group_name": data.group_name,
                }
                for html_element_id, data in enumerate(associate_data, start=1)
            ]
        except Exception as get_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"getting associate error {get_sql_error}")
            db.session.rollback()


# print(create_associate_user_group(device_id=92, group_id=1, user_id=2))
# print(get_associate_user_group(2))


def delete_associate_user_group(associate_id: int):
    """
    This function is needed to delete user role from db
    Parm:
        id: int
    return:
        bool
    """
    try:
        GropupPermition.query.filter_by(id=int(associate_id)).delete()
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


def update_associate_user_group(associate_id: int, device_id: int, group_id: int) -> bool:
    """
    This function update a associate to the DB
    parm:
        associate_id: int
        device_id: int
        group_id: int
    return:
        bool
    """
    try:
        # Getting device data from db
        data = db.session.query(GropupPermition).filter_by(id=int(associate_id)).first()
        if data.group_id != group_id:
            data.group_id = group_id
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


def get_user_roles():
    """
    Get all Roles
    """
    roles = UserRoles.query.order_by(UserRoles.id)

    return [
        {
            "html_element_id": html_element_id,
            "role_id": role.id,
            "role_name": role.role_name,
        }
        for html_element_id, role in enumerate(roles, start=1)
    ]


def get_devices():
    """
    Get all Roles
    """
    devices = (
        Devices.query.with_entities(Devices.id, Devices.device_hostname, Devices.device_ip)
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