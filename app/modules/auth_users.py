import re
from werkzeug.security import generate_password_hash, check_password_hash

from app.models import Users
from app import db, logger


class AuthUsers:
    """Class"""

    def __init__(
        self,
        username: str = None,
        email: str = None,
        role: str = "admin",
        password: str = None,
        user_id: str = None,
    ):
        self.username = username
        self.email = email
        self.role = role
        self.password = password
        self.user_id = user_id

    @staticmethod
    def _check_user_exist_by_email(email: str) -> bool:
        """
        This function is needed to check user exist
        Parm:
            email: str
        return:
            bool
        """
        email_regex = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        if re.fullmatch(email_regex, email):
            user = Users.query.filter_by(email=email).first()
            return True if user else False
        else:
            return False

    @staticmethod
    def _check_user_exist_by_id(user_id: str) -> bool:
        """
        This function is needed to check user exist
        Parm:
            user_id: str
        return:
            bool
        """
        user = Users.query.filter_by(id=int(user_id)).first()
        return True if user else False

    def add_user(self) -> bool:
        """
        This function writes a new user on db id user is not exist
        """

        checking_user = self._check_user_exist_by_email(self.email)
        if checking_user is False:
            #
            user = Users(
                email=self.email,
                password=generate_password_hash(self.password, method="sha256"),
                username=self.username,
                role=self.role,
            )
            #
            try:
                # Sending data in BD
                db.session.add(user)
                # Committing changes
                db.session.commit()
                logger.info(f"User {self.email} has been added")
                return True
            #
            except Exception as write_sql_error:
                # If an error occurs as a result of writing to the DB,
                # then rollback the DB and write a message to the log
                logger.info(f"User {self.email} was not added. Error {write_sql_error}")
                db.session.rollback()
                return False
        #
        else:
            return False

    def update_user(self) -> bool:
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
        checking_user = self._check_user_exist_by_id(self.user_id)
        if checking_user:
            try:
                # Getting device data from db
                data = db.session.query(Users).filter_by(id=int(self.user_id)).first()
                if data.email != self.email:
                    data.email = self.email
                if (
                    not check_password_hash(data.password, self.password)
                    and self.password != ""
                ):
                    password = generate_password_hash(self.password, method="sha256")
                    data.password = password
                if data.username != self.username:
                    data.username = self.username
                if data.role != self.role:
                    data.role = self.role

                # Apply changing
                db.session.commit()
                logger.info(f"User {self.email} has been updated")
                return True

            except Exception as update_sql_error:
                # If an error occurs as a result of writing to the DB,
                # then rollback the DB and write a message to the log
                logger.info(
                    f"User {self.email} was not updated. Error {update_sql_error}"
                )
                db.session.rollback()
                return False

        return False

    def del_user(self) -> bool:
        """
        This function is needed to delete user
        Parm:
            user_id: str
        return:
            bool
        """
        checking_user = self._check_user_exist_by_id(self.user_id)
        if checking_user:
            try:
                Users.query.filter_by(id=int(self.user_id)).delete()
                db.session.commit()
                logger.info(f"User {self.email} has been deleted")
                return True
            except Exception as delete_device_error:
                db.session.rollback()
                print(delete_device_error)
                logger.info(
                    f"User {self.email} was not deleted. Error {delete_device_error}"
                )
                return False

    def check_user(self) -> bool and str:
        """
        This function is needed to check and authorization username and password
        Parm:
            email: str
            password: str
        return:
            bool
        """
        user = Users.query.filter_by(email=self.email).first()
        return (
            True
            if user and check_password_hash(user.password, self.password)
            else False
        )

    @staticmethod
    def get_users_list() -> dict:
        """
        This function returns all users from the database
        """
        db_users = Users.query.order_by(Users.id)
        users_dict = {}
        for users_count, db_user in enumerate(db_users, start=1):
            users_dict.update(
                {
                    db_user.id: {
                        "users_count": users_count,
                        "username": db_user.username,
                        "email": db_user.email,
                        "role": db_user.role,
                    }
                }
            )
        return users_dict

    def del_user_by_email(self) -> bool:
        """
        This function is needed to delete user
        Parm:
            user_id: str
        return:
            bool
        """
        checking_user = check_user_exist_by_email(self.email)
        if checking_user:
            try:
                Users.query.filter_by(email=self.email).delete()
                db.session.commit()
                logger.info(f"User {self.email} has been deleted")
                return True
            except Exception as delete_device_error:
                db.session.rollback()
                logger.info(
                    f"User {self.email} was not deleted. Error {delete_device_error}"
                )
                return False


#
def add_user(email: str, password: str, username: str, role: str) -> bool:
    """
    This function writes a new user on db id user is not exist
    """

    checking_user = check_user_exist_by_email(email)
    if checking_user is False:
        #
        user = Users(
            email=email,
            password=generate_password_hash(password, method="sha256"),
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


def update_user(
    user_id: str, email: str, password: str, username: str, role: str
) -> bool:
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
            if not check_password_hash(data.password, password) and password != "":
                password = generate_password_hash(password, method="sha256")
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


def del_user(user_id: str) -> bool:
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


def check_user_exist_by_email(email: str) -> bool:
    """
    This function is needed to check user exist
    Parm:
        email: str
    return:
        bool
    """
    user = Users.query.filter_by(email=email).first()
    return True if user else False


def check_user_exist_by_id(user_id: str) -> bool:
    """
    This function is needed to check user exist
    Parm:
        user_id: str
    return:
        bool
    """
    user = Users.query.filter_by(id=int(user_id)).first()
    return True if user else False


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
    return True if user and check_password_hash(user.password, password) else False


# def get_users_list():
#     return Users.query.order_by(Users.id)
def get_users_list() -> dict:
    """
    This function returns all users from the database
    """
    db_users = Users.query.order_by(Users.id)
    users_dict = {}
    for users_count, db_user in enumerate(db_users, start=1):
        users_dict.update(
            {
                db_user.id: {
                    "users_count": users_count,
                    "username": db_user.username,
                    "email": db_user.email,
                    "role": db_user.role,
                }
            }
        )
    return users_dict
