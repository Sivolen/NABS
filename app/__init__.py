# import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import test_env_release

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s %(levelname)s %(name)s %(threadName)s: %(message)s"
# )

# Init flask app
app = Flask(__name__)

# Add config parameters in flask app and chose release
app.config.from_object(f"app.configuration.{test_env_release}")

# Init DB on Flask app
db = SQLAlchemy(app)
# Add migrate DB
migrate = Migrate(app, db)
# db.init_app(app)

# import routes
from app import views, models
