from app import logger
from ldap3 import Server, Connection, ALL
from flask import session, redirect, url_for
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
def check_auth(function):
    def wrapper_function(*args, **kwargs):
        if "user" not in session or session["user"] == "":
            return redirect(url_for("login"))
        else:
            return function(*args, **kwargs)

    wrapper_function.__name__ = function.__name__
    return wrapper_function
