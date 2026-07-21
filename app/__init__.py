import os

from flask import Flask, render_template

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import release_options

from app.modules.logger import setup_logging

__version__ = "2.5.3"
__ui__ = "2.5.3"
__version_date__ = "2026-07-21"
__author__ = "Gridnev Anton"
__description__ = "NABS"
__license__ = "MIT"
__url__ = "https://github.com/Sivolen/NABS"


# Init logging
# valid log levels ("DEBUG", "INFO", "WARNING", "ERROR")
logger = setup_logging(log_level="INFO")

# Init flask app
app = Flask(__name__)
# app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
Compress(app)
# Add config parameters in flask app and chose release
app.config.from_object(f"app.configuration.{release_options}")

# Enable CSRF protection for all POST/PUT/PATCH/DELETE requests.
# Templates must include {{ csrf_token() }} in forms, and AJAX calls must
# send the X-CSRFToken header (see the fetch wrapper in base.html).
csrf = CSRFProtect(app)
@csrf.error_handler
def csrf_error(reason):
    return render_template('csrf_error.html', reason=reason), 400

# Init DB on Flask app
db = SQLAlchemy(app)
# Add migrate DB
migrate = Migrate(app, db)
# db.init_app(app)
from app import routes, models

# Exempt AJAX endpoints from CSRF — they use authentication decorators instead.
from app.views.previous_config import previous_config

csrf.exempt(previous_config)

# Run scheduler for backup configuration
import scheduler

scheduler.init_scheduler(app)

# Create a default administrator user if no user with the 'sadmin' role exists.

if not os.environ.get("FLASK_ENV") == "testing":
    from app.modules.setup import ensure_default_admin

    ensure_default_admin()
