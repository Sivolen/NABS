from werkzeug.security import generate_password_hash, check_password_hash

from app.models import Users
from app import db


def add_user(email: str, password: str, username: str, role: str) -> bool:
    """
     This function writes a new user on db id user is not exist
    """

    checking_user = check_user_exist(email)
    if checking_user is False:
        #
        user = Users(
            email=email,
            password=generate_password_hash(password, method='sha256'),
            username=username,
            role=role,
        )
        #
        try:
            # Sending data in BD
            db.session.add(user)
            # Committing changes
            db.session.commit()
            return True
        #
        except Exception as write_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            print(write_sql_error)
            db.session.rollback()
            return False
    #
    else:
        return False


def update_user(user_id: str, email: str, password: str, username: str, role: str) -> bool:
    """
    This function update a user data
    parm:
        email: str
        password: str
        username: str
        username: str
    return:
        None
    """
    checking_user = check_user_exist_by_id(user_id)
    if checking_user:
        try:
            # Getting device data from db
            data = db.session.query(Users).filter_by(id=int(user_id)).first()
            if data.email != email:
                data.email = email
            if not check_password_hash(data.password, password) and password != '':
                password = generate_password_hash(password, method='sha256')
                data.password = password
            if data.username != username:
                data.username = username
            if data.role != role:
                data.role = role

            # Apply changing
            db.session.commit()
            return True

        except Exception as update_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            print(update_sql_error)
            db.session.rollback()
            return False

    return False


def del_user(user_id: str):
    """
    This function is needed to delete user
    Parm:
        user_id: str
    return:
        bool
    """
    checking_user = check_user_exist_by_id(user_id)
    if checking_user:
        try:
            Users.query.filter_by(id=int(user_id)).delete()
            db.session.commit()
            return True
        except Exception as delete_device_error:
            db.session.rollback()
            print(delete_device_error)
            return False


def check_user_exist(email: str) -> bool:
    """
    This function is needed to check user exist
    Parm:
        email: str
    return:
        bool
    """
    user = Users.query.filter_by(email=email).first()

    if user:
        return True
    else:
        return False


def check_user_exist_by_id(user_id: str) -> bool:
    """
    This function is needed to check user exist
    Parm:
        user_id: str
    return:
        bool
    """
    user = Users.query.filter_by(id=int(user_id)).first()
    if user:
        return True
    else:
        return False


def check_user(email: str, password: str) -> bool and str:
    """
    This function is needed to check and authorization username and password
    Parm:
        email: str
        password: str
    return:
        bool
    """
    user = Users.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        return True
    else:
        return False


def get_users_list():
    return Users.query.order_by(Users.id)
