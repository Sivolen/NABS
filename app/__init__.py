# import logging

from flask import Flask

# from quart import Quart
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress

from config import release_options

from app.modules.logger import setup_logging

__version__ = "1.5.2"
__version_date__ = "2023-05-08"
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
Compress(app)
# Add config parameters in flask app and chose release
app.config.from_object(f"app.configuration.{release_options}")

# Init DB on Flask app
db = SQLAlchemy(app)
# Add migrate DB
migrate = Migrate(app, db)
# db.init_app(app)

# import routes
from app import views, models
