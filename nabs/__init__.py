from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import test_env_release

# Init flask app
app = Flask(__name__)

# Add config parameters in flask app and chose release
app.config.from_object(f"nabs.configuration.{test_env_release}")

# Init DB on Flask app
db = SQLAlchemy(app)

# db.init_app(app)

# import routes
from nabs import views
