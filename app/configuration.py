from config import token


class Config(object):
    """
    Configuration base, for all environments
    """
    DEBUG = False
    TESTING = False
    # We add a secret token, it is necessary for user authorization through LDAP to work
    SECRET_KEY = token
    CSRF_ENABLED = True
    # Default parameter SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Fix SESSION_COOKIE_SAMESITE
    SESSION_COOKIE_SAMESITE = "Strict"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "max_overflow": 15,
        "pool_pre_ping": True,
        "pool_recycle": 60 * 60,
        "pool_size": 30,
    }


class ProductionConfig(Config):
    # Adding DB file on flask app
    SQLALCHEMY_DATABASE_URI = "postgresql://nabs:nabs@localhost:5432/nabs"
    # Fix SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    # Adding DB file on flask app
    SQLALCHEMY_DATABASE_URI = "sqlite:///devices.db"
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
