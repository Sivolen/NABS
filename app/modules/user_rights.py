from app.models import Users
from app import logger

from flask import session, redirect, url_for


def check_user_rights(user_email: str) -> str:
    """
    This function is needed to check user rights
    Parm:
        user_email: str
    return:
        str
    """
    user_right = Users.query.with_entities(Users.role).filter_by(email=user_email).first()
    return user_right["role"] if user_right is not None else "user"


# Decorator for check authorizations users
def check_user_role(function):
    def wrapper_function(*args, **kwargs):
        if "rights" not in session or session["rights"] == "" or session["rights"] == "user":
            logger.info(f"{session}, {function.__name__}")
            return redirect(url_for("devices"))
            # return render_template('login.html')
        else:
            logger.info(f"{session}, {function.__name__}")
            return function(*args, **kwargs)

    wrapper_function.__name__ = function.__name__
    return wrapper_function
