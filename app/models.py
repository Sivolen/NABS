from app import db
from datetime import datetime

# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


class Devices(db.Model):
    """
    Class DB for devices profiles
    """

    # Add id in DB
    id = db.Column(db.Integer, primary_key=True)
    # Add device ip DB
    device_ip = db.Column(db.String, index=True, nullable=False)
    # Add device hostname ip DB
    device_hostname = db.Column(db.String(50), index=True, nullable=True)
    # Add device env in DB
    device_vendor = db.Column(db.String(100), index=True, nullable=True)

    device_model = db.Column(db.String(200), index=True, nullable=True)

    device_os_version = db.Column(db.String(100), index=True, nullable=True)

    device_sn = db.Column(db.String(100), index=True, nullable=True)

    device_uptime = db.Column(db.String(100), index=True, nullable=True)

    # Add timestamp in DB
    timestamp = db.Column(db.String(20), default=timestamp)

    connection_status = db.Column(db.String(50), index=True, nullable=True)

    connection_driver = db.Column(db.String(50), index=True, nullable=True)

    # Return format massages from DB
    def __repr__(self):
        return "<Devices %r>" % self.device_ip


class Configs(db.Model):
    """
    Class DB for configs file
    """

    # Add id in DB
    id = db.Column(db.Integer, primary_key=True)
    # Add timestamp in DB
    timestamp = db.Column(db.String(20), index=True, default=timestamp)
    # Add device config file in DB
    device_config = db.Column(db.Text, nullable=False)
    # Add device ip DB
    device_ip = db.Column(db.Text, index=True, nullable=False)
    # device_ip = db.Column(
    #     db.String, db.ForeignKey("devices.device_ip", name="test"), nullable=False
    # )
    # Return format massages from DB

    def __repr__(self):
        return "<Configs %r>" % self.device_ip
