from app.models import UserRoles
from app import db, logger


def create_user_role(role_name: str):
    """
    This function create a new user role to the database.
    Need to parm:
    role_name: str
    return:
        Bool
    """
    role_name = UserRoles(
        group_name=role_name,
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


def delete_user_role(role_id: int):
    pass


def update_user_role(role_id: int):
    pass


def associate_user_role(role_id: int, user_id: int):
    pass

