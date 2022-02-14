from ldap3 import Server, Connection, ALL
from flask import session, redirect, url_for
from config import *


class LDAP_FLASK:
    # Init class and overriding variables
    def __init__(self, user_login, user_password):
        self.AD_SERVER = AD_ADDRESS
        self.AD_USER = user_login
        self.AD_PASSWORD = user_password
        self.AD_SEARCH_TREE = AD_SEARCH_TREE
        self.server = Server(self.AD_SERVER, get_info=ALL, use_ssl=False, port=389)

    # Connecting to ldap server, if connected then return True
    def bind(self):
        try:
            Connection(self.server, user=self.AD_USER, password=self.AD_PASSWORD, version=3,
                       auto_bind=True)
            return True
        except:
            return False


# Decorator for check authorizations users
def check_auth(function):
    def wrapper_function(*args, **kwargs):
        if 'user' not in session or session['user'] == "":
            return redirect(url_for('login'))
            # return render_template('login.html')
        else:
            # session['info'] = DB_FLASK().search_user(session['user'])
            return function(*args, **kwargs)

    wrapper_function.__name__ = function.__name__
    return wrapper_function
