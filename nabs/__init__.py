from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import test_env_release

# Init flask app
app = Flask(__name__)

# # We add a secret token, it is necessary for user authorization through LDAP to work
# app.config["SECRET_KEY"] = token
# # Fix SESSION_COOKIE_SAMESITE
# app.config.update(SESSION_COOKIE_SAMESITE="Strict")
# # Adding DB file on flask app
# # {Path(__file__).parent.parent}/
# app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///devices.db"
# # Fix SQLALCHEMY_TRACK_MODIFICATIONS
# app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Add config parameters in flask app and chose release
app.config.from_object(f'nabs.configuration.{test_env_release}')

# Init DB on Flask app
db = SQLAlchemy(app)

# db.init_app(app)

# import routes
from nabs import view
