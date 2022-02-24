from nabs import db
from datetime import datetime

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

