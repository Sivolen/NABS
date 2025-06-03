from app import logger
from ldap3 import Server, Connection, ALL
from flask import session, redirect, url_for, request, flash
from functools import wraps

from config import AD_ADDRESS, AD_PORT, AD_USE_SSL, AD_SEARCH_TREE


class LdapFlask:
    # Init class and overriding variables
    def __init__(self, user_login, user_password):
        self.AD_SERVER = AD_ADDRESS
        self.AD_USER = user_login
        self.AD_PASSWORD = user_password
        self.AD_SEARCH_TREE = AD_SEARCH_TREE
        self.server = Server(
            self.AD_SERVER, get_info=ALL, use_ssl=AD_USE_SSL, port=AD_PORT
        )

    # Connecting to ldap server, if connected then return True
    def bind(self) -> bool:
        try:
            Connection(
                self.server,
                user=self.AD_USER,
                password=self.AD_PASSWORD,
                version=3,
                auto_bind="NO_TLS",
            )
            return True
        except Exception as e:
            logger.debug(f"Error connecting to ldap server {e}")
            return False


# Decorator for check authorizations users
# def check_auth(function):
#     def wrapper_function(*args, **kwargs):
#         if "user" not in session or session["user"] == "":
#             return redirect(url_for("login"))
#         else:
#             return function(*args, **kwargs)
#
#     wrapper_function.__name__ = function.__name__
#     return wrapper_function
def check_auth(function):
    """
    Decorator for checking user authorization.

    Checks:
    1. User presence in session
    2. Non-empty login value
    3. Additional checks (optional)

    If user is not authorized:
    - Redirects to login page
    - Adds message for user
    - Saves URL for redirect after login
    """

    @wraps(function)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            # Save the target URL in the 'next' parameter
            session["next_url"] = request.url
            flash("To access you need to log in", "warning")
            logger.info(
                f"{session.get('user', 'anonymous')} Redirecting to login, next_url: {request.url}"
            )
            return redirect(url_for("login", next=request.url))
        return function(*args, **kwargs)

    return wrapper


def is_authenticated():
    return "user" in session and session["user"]
