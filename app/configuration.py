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
    SQLALCHEMY_ENGINE_OPTIONS = {
        "max_overflow": 15,
        "pool_pre_ping": True,
        "pool_recycle": 60 * 60,
        "pool_size": 30,
    }
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DBUser}:{DBPassword}@{DBHost}:{DBPort}/{DBName}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = PERMANENT_SESSION_LIFETIME  # передаём дальше


class DevelopmentConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///devices.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False