from flask import Flask
# from nabs.database import db
from config import token
from flask_sqlalchemy import SQLAlchemy

# Init flask app
app = Flask(__name__)
# We add a secret token, it is necessary for user authorization through LDAP to work
app.config["SECRET_KEY"] = token
# Fix SESSION_COOKIE_SAMESITE
app.config.update(SESSION_COOKIE_SAMESITE="Strict")
# Adding DB file on flask app
# {Path(__file__).parent.parent}/
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///devices.db"
# Fix SQLALCHEMY_TRACK_MODIFICATIONS
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Init DB on Flask app
db = SQLAlchemy(app)

# db.init_app(app)

from nabs import view
