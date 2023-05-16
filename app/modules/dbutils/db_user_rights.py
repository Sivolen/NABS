from app.models import Users
from app import logger

from flask import session, redirect, url_for, flash

from app.modules.dbutils.db_users_permission import check_allowed_device


def check_user_rights(user_email: str) -> str:
    """
    This function is needed to check user rights
    Parm:
        user_email: str
    return:
        str
    """
    user_right = (
        Users.query.with_entities(Users.role).filter_by(email=user_email).first()
    )
    return user_right["role"] if user_right is not None else "user"


# Decorator for check authorizations users
def check_user_role_redirect(function):
    def wrapper_function(*args, **kwargs):
        if (
            "rights" not in session
            or session["rights"] == ""
            or not session["rights"] == "sadmin"
        ):
            logger.info(f"{session}, {function.__name__}")
            return redirect(url_for("devices"))
        else:
            logger.info(f"{session}, {function.__name__}")
            return function(*args, **kwargs)

    wrapper_function.__name__ = function.__name__
    return wrapper_function


# Decorator for checking user authorization and blocking if the user does not have enough rights
def check_user_role_block(function):
    def wrapper_function(*args, **kwargs):
        if (
            "rights" not in session
            or session["rights"] == ""
            or not session["rights"] in ["sadmin", "admin"]
        ):
            logger.info(f"Deny: {session}, {function.__name__}")
            return f"Access dined {session}"
            # return render_template('login.html')
        else:
            logger.info(f"Permit: {session}, {function.__name__}")
            return function(*args, **kwargs)

    wrapper_function.__name__ = function.__name__
    return wrapper_function


def check_user_permission(function):
    def wrapper_function(*args, **kwargs):
        device_id = int(kwargs.get("device_id"))
        check_device = check_allowed_device(
            groups_id=session["allowed_devices"], device_id=device_id
        )
        if session["rights"] == "sadmin":
            return function(*args, **kwargs)
        elif (
            "allowed_devices" not in session
            or session["allowed_devices"] == ""
            or check_device is False
        ):
            logger.info(f"{session}, {function.__name__}")
            flash("View config for this device is not allowed", "warning")
            return redirect(url_for("devices"))
        else:
            logger.info(f"{session}, {function.__name__}")
            return function(*args, **kwargs)

    wrapper_function.__name__ = function.__name__
    return wrapper_function
