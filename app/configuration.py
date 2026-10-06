from config import (
    TOKEN,
    DBHost,
    DBPort,
    DBName,
    DBUser,
    DBPassword,
    BEHIND_PROXY,
    PERMANENT_SESSION_LIFETIME,
)
import config as _config
from app.modules.db_pool import database_url, engine_options

# Optional pool settings of config.py (an old config.py without them keeps working)
_POOL_SETTINGS = {
    name: getattr(_config, name, None)
    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
    )
}


class Config(object):
    """
    Configuration base, for all environments
    """

    DEBUG = False
    TESTING = False

    SECRET_KEY = TOKEN

    # CSRF settings
    WTF_CSRF_ENABLED = True
    WTF_CSRF_HEADERS = ["X-CSRF-Token"]
    WTF_CSRF_TIME_LIMIT = PERMANENT_SESSION_LIFETIME  # 8 часов
    WTF_CSRF_SSL_STRICT = False
    WTF_CSRF_METHODS = ["POST", "PUT", "PATCH", "DELETE"]

    # Session settings - зависят от BEHIND_PROXY
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = BEHIND_PROXY

    # URL scheme
    PREFERRED_URL_SCHEME = "https" if BEHIND_PROXY else "http"

    # SQLAlchemy
    SQLALCHEMY_TRACK_MODIFICATIONS = True


class ProductionConfig(Config):
    # Every process (each gunicorn worker, the scheduler) has its OWN pool of at most
    # pool_size + max_overflow connections. See app/modules/db_pool.py for the budget
    # and scripts/check_db_connections.py to check it against max_connections.
    SQLALCHEMY_ENGINE_OPTIONS = engine_options(_POOL_SETTINGS)
    # percent-encoded: a password with @ / : % # ? must not break the URL
    SQLALCHEMY_DATABASE_URI = database_url(DBUser, DBPassword, DBHost, DBPort, DBName)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = PERMANENT_SESSION_LIFETIME  # передаём дальше


class DevelopmentConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///devices.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
