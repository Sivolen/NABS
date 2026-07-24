import os

from flask import Flask

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import release_options, BEHIND_PROXY

from app.modules.logger import setup_logging

__version__ = "2.6.0"
__ui__ = "2.6.1"
__version_date__ = "2026-07-24"
__author__ = "Gridnev Anton"
__description__ = "NABS"
__license__ = "MIT"
__url__ = "https://github.com/Sivolen/NABS"


# Init logging
logger = setup_logging(log_level="INFO")

# Init flask app
app = Flask(__name__)

# ProxyFix - только если за прокси
if BEHIND_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

Compress(app)

# Загружаем конфиг - ВСЕ настройки в одном месте
app.config.from_object(f"app.configuration.{release_options}")

# CSRF Protection
csrf = CSRFProtect(app)

# Init DB
db = SQLAlchemy(app)
migrate = Migrate(app, db)

from app import routes, models

# Run scheduler
import scheduler

scheduler.init_scheduler(app)

# Create default admin
if not os.environ.get("FLASK_ENV") == "testing":
    from app.modules.setup import ensure_default_admin

    ensure_default_admin()
