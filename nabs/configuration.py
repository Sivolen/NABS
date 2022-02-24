from config import token


class Config(object):
    """
    Configuration base, for all environments
    """

    DEBUG = False
    TESTING = False
    # Adding DB file on flask app
    SQLALCHEMY_DATABASE_URI = "sqlite:///devices.db"
    BOOTSTRAP_FONTAWESOME = True
    # We add a secret token, it is necessary for user authorization through LDAP to work
    SECRET_KEY = token
    CSRF_ENABLED = True
    # Default parameter SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Fix SESSION_COOKIE_SAMESITE
    SESSION_COOKIE_SAMESITE = "Strict"


class ProductionConfig(Config):
    # SQLALCHEMY_DATABASE_URI = 'mysql://user@localhost/foo'
    # Fix SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
