from config import TOKEN, DBHost, DBPort, DBName, DBUser, DBPassword


class Config(object):
    """
    Configuration base, for all environments
    """

    DEBUG = False
    TESTING = False
    # We add a secret TOKEN, it is necessary for user
    # authorization through LDAP to work
    SECRET_KEY = TOKEN
    CSRF_ENABLED = True
    # Default parameter SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Fix SESSION_COOKIE_SAMESITE
    SESSION_COOKIE_SAMESITE = "Strict"


class ProductionConfig(Config):
    SQLALCHEMY_ENGINE_OPTIONS = {
        "max_overflow": 15,
        "pool_pre_ping": True,
        "pool_recycle": 60 * 60,
        "pool_size": 30,
    }
    # Adding DB file on flask app
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DBUser}:{DBPassword}@{DBHost}:{DBPort}/{DBName}"
    )
    # Fix SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    # Adding DB file on flask app
    SQLALCHEMY_DATABASE_URI = "sqlite:///devices.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
