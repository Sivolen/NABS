from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from pathlib import Path
from config import token

# Init flask app
app = Flask(__name__)
# We add a secret token, it is necessary for user authorization through LDAP to work
app.config["SECRET_KEY"] = token
# Fix SESSION_COOKIE_SAMESITE
app.config.update(SESSION_COOKIE_SAMESITE="Strict")
# Adding DB file on flask app
app.config[
    "SQLALCHEMY_DATABASE_URI"
] = f"sqlite:///{Path(__file__).parent.parent}/devices.db"
# Fix SQLALCHEMY_TRACK_MODIFICATIONS
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Init DB on Flask app
db = SQLAlchemy(app)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


class Devices(db.Model):
    """
    Class DB for devices profiles
    """

    id = db.Column(db.Integer, primary_key=True)
    device_ip = db.Column(db.Integer, index=True, nullable=False)
    device_hostname = db.Column(db.String(50), index=True, nullable=True)
    # device_env = db.Column(db.String(100), index=True, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now())

    def __repr__(self):
        return "<Devices %r>" % self.device_ip


class Configs(db.Model):
    """
    Class DB for configs file
    """

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now())
    device_config = db.Column(db.Text, nullable=False)
    device_ip = db.Column(db.Integer, db.ForeignKey("devices.device_ip"))

    def __repr__(self):
        return "<Configs %r>" % self.device_ip


# The function gets the latest configuration file from the database for the provided device
def get_last_config_for_device(ipaddress: str) -> dict or None:
    """
    Need to parm:
    Ipaddress
    """
    try:
        # Get last configurations from DB
        data = (
            Configs.query.order_by(Configs.timestamp.desc())
            .filter_by(device_ip=ipaddress)
            .first()
        )
        # Variable for device configuration
        db_last_config = data.device_config
        # Variable to set the timestamp
        db_last_timestamp = data.timestamp
        return {"last_config": db_last_config, "timestamp": db_last_timestamp}
    except:
        # If configuration not found return None
        return None


# This function gets all timestamps for which there is a configuration for this device
def get_all_cfg_timestamp_for_device(ipaddress: str) -> list or None:
    """
    Need to parm:
    Ipaddress
    """
    try:
        # Gets all timestamp from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress
        )
        return [db_timestamp.timestamp for db_timestamp in data[1:]]
    except:
        # If timestamp not found return None
        return None


# This function gets the previous config for this device from the DB
def get_previous_config(ipaddress: str, db_timestamp: str) -> str or None:
    """
    Need to parm:
    Ipaddress and timestamp
    """
    try:
        # Get configurations from DB
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress, timestamp=db_timestamp
        )
        # The database returns a list, we get text data from it and return it from the function
        return data[0].device_config
    except:
        # If config not found return None
        return None


# This function writes a new configuration file to the DB
def write_cfg_on_db(ipaddress: str, config: str) -> None:
    """
    Need to parm:
    Ipaddress and config, timestamp generated automatically
    """
    # We form a request to the database and pass the IP address and device configuration
    config = Configs(device_ip=ipaddress, device_config=config)
    try:
        # Sending data in BD
        db.session.add(config)
        # Committing changes
        db.session.commit()
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        print(write_sql_error)
        db.session.rollback()
