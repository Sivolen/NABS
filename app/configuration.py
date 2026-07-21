from config import TOKEN, DBHost, DBPort, DBName, DBUser, DBPassword, NABS_DOMAIN


class Config(object):
    """
    Configuration base, for all environments
    """

    DEBUG = False
    TESTING = False
    # We add a secret TOKEN, it is necessary for user
    # authorization through LDAP to work
    SECRET_KEY = TOKEN
    # NOTE: 'CSRF_ENABLED' is not a real Flask-WTF setting (the correct key is
    # WTF_CSRF_ENABLED, which Flask-WTF's CSRFProtect reads). Kept here only
    # for backwards compatibility with anything that might reference it.
    CSRF_ENABLED = True
    WTF_CSRF_ENABLED = True
    # Allow CSRF token in X-CSRF-Token header for AJAX requests
    WTF_CSRF_HEADERS = ["X-CSRF-Token"]
    # Default parameter SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Fix SESSION_COOKIE_SAMESITE
    SESSION_COOKIE_SAMESITE = "Lax"
    # SESSION_COOKIE_SECURE = True


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
    SESSION_COOKIE_SECURE = True
    PERMANENT_SESSION_LIFETIME = 86400
    SESSION_COOKIE_DOMAIN = NABS_DOMAIN


class DevelopmentConfig(Config):
    # Adding DB file on flask app
    SQLALCHEMY_DATABASE_URI = "sqlite:///devices.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
