from sqlalchemy import text

from app.models import Credentials
from app.modules.crypto import encrypt

from app import db, logger

from config import TOKEN


def check_credentials(credentials_name: str) -> int or None:
    return (
        Credentials.query.with_entities(Credentials.credentials_name)
        .filter_by(credentials_name=credentials_name)
        .first()
    )


def add_credentials(
    credentials_name: str,
    credentials_username: str,
    credentials_password: str,
    credentials_user_group: int,
) -> bool:
    """
    This function adds a new credentials to the database. Need to parm:
    credentials_name: str
    credentials_username: str
    credentials_password: str
    return:
        None
    """
    # We form a request to the database and pass the credentials
    credentials_data = Credentials(
        credentials_name=credentials_name,
        credentials_username=credentials_username,
        credentials_password=credentials_password,
        user_group_id=credentials_user_group,
    )
    try:
        # Sending data in BD
        db.session.add(credentials_data)
        # Committing changes
        db.session.commit()
        return True
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Adds credentials error {write_sql_error}")
        db.session.rollback()
        return False


def del_credentials(credentials_id: int) -> bool:
    """
    This function is needed to delete credentials from db
    Parm:
        credentials_id: int
    return:
        bool
    """
    try:
        Credentials.query.filter_by(id=int(credentials_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_credentials_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        db.session.rollback()
        logger.info(
            f"Delete credentials id {credentials_id} error {delete_credentials_error}"
        )
        return False


def update_credentials(
    credentials_id: int,
    credentials_name: str,
    credentials_username: str,
    credentials_password: str,
    credentials_user_group: int,
) -> bool or None:
    """
    This function update a credentials to the DB
    parm:
        credentials_id: int
        credentials_name: str
        credentials_username: str
        credentials_password: str
    return:
        bool
    """
    if not isinstance(credentials_id, int) or credentials_id is None:
        logger.info(f"Update credentials error, credentials_id must be an integer")
        return None
    try:
        # Getting device data from db
        credentials_data = (
            db.session.query(Credentials).filter_by(id=int(credentials_id)).first()
        )
        if credentials_password is not None:
            credentials_password = encrypt(ssh_pass=credentials_password, key=TOKEN)
        if credentials_data.credentials_name != credentials_name:
            credentials_data.credentials_name = credentials_name
        if credentials_data.credentials_username != credentials_username:
            credentials_data.credentials_username = credentials_username
        if credentials_data.credentials_password != credentials_password:
            credentials_data.credentials_password = credentials_password
        if credentials_data.user_group_id != credentials_user_group:
            credentials_data.user_group_id = credentials_user_group

        # Apply changing
        db.session.commit()
        return True

    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update credentials error {update_sql_error}")
        db.session.rollback()
        return False


def get_all_credentials() -> list:
    """
    This function return all credentials
    """
    credentials = Credentials.query.order_by(Credentials.id)
    return [
        {
            "html_element_id": html_element_id,
            "credentials_id": group.id,
            "credentials_name": group.credentials_name,
            "credentials_username": group.credentials_username,
            "credentials_password": group.credentials_password,
            "credentials_user_group": group.user_group_id,
        }
        for html_element_id, group in enumerate(credentials, start=1)
    ]


def get_credentials(credentials_id: int) -> dict:
    """
    This function return credentials
    """
    credentials = (
        Credentials.query.with_entities(
            Credentials.id,
            Credentials.credentials_name,
            Credentials.credentials_username,
            Credentials.credentials_password,
            Credentials.user_group_id,
        )
        .filter_by(id=credentials_id)
        .first()
    )
    return {
        "credentials_id": credentials.id,
        "credentials_name": credentials.credentials_name,
        "credentials_username": credentials.credentials_username,
        "credentials_password": credentials.credentials_password,
        "credentials_user_group": credentials.user_group_id,
    }


def get_allowed_credentials(user_id: int) -> list:
    """
    This function needs to get allowed credentials for a user
    """
    if isinstance(user_id, int) and user_id is not None:
        try:
            slq_request = text(
                "select "
                "credentials.id, "
                "credentials.credentials_name, "
                "credentials.credentials_username, "
                "credentials.user_group_id "
                "from credentials "
                "left join group_permission on group_permission.user_group_id = credentials.user_group_id  "
                "where group_permission.user_id = :user_id"
            )
            parameters = {"user_id": user_id}
            credentials_data = db.session.execute(slq_request, parameters).fetchall()
            return [
                {
                    "html_element_id": html_element_id,
                    "credentials_id": i["id"],
                    "credentials_name": i["credentials_name"],
                    "credentials_username": i["credentials_username"],
                }
                for html_element_id, i in enumerate(credentials_data)
            ]

        except Exception as get_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"getting allowed credentials error {get_sql_error}")
