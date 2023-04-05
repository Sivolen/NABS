from app.models import UserRoles
from app import db, logger


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
        user_group_id: int
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


def get_user_roles() -> list:
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
    ] if roles is not None else None
