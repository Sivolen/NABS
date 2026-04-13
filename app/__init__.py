from flask import Flask

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress

from config import release_options

from app.modules.logger import setup_logging

__version__ = "2.5.0"
__ui__ = "2.5.0"
__version_date__ = "2026-04-13"
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
from app import routes, models

import scheduler
scheduler.init_scheduler(app)   # создаёт планировщик и сохраняет в app.scheduler (или глобально)

from app.modules.dbutils.db_scheduler import init_default_scheduler_settings
from app.modules.scheduler_manager import update_scheduler_job

with app.app_context():
    init_default_scheduler_settings()
    update_scheduler_job()

# Запускаем планировщик только в основном процессе (при preload)
import os
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    # Для Gunicorn с preload это сработает один раз
    sched = scheduler.get_scheduler()
    if sched and not sched.running:
        sched.start()
        app.logger.info("Scheduler started.")