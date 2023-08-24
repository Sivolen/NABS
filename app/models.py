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
    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    # Add device ip DB
    device_ip = db.Column(db.String(100), index=True, nullable=True, primary_key=True)
    # Add device hostname ip DB
    device_hostname = db.Column(db.String(100), index=True, nullable=True)
    # Add device env in DB
    device_vendor = db.Column(db.String(100), index=True, nullable=True)

    device_model = db.Column(db.String(100), index=True, nullable=True)

    device_os_version = db.Column(db.String(150), index=True, nullable=True)

    device_sn = db.Column(db.String(100), index=True, nullable=True)

    device_uptime = db.Column(db.String(50), index=True, nullable=True)

    # Add timestamp in DB
    timestamp = db.Column(db.String(50), default=timestamp)

    connection_status = db.Column(db.String(100), index=True, nullable=True)

    connection_driver = db.Column(db.String(20), index=True, nullable=True)

    group_id = db.Column(db.Integer, nullable=True)

    ssh_user = db.Column(db.String(100), index=True, nullable=True)
    ssh_pass = db.Column(db.String(100), index=True, nullable=True)
    ssh_port = db.Column(db.Integer, nullable=True)

    credentials_id = db.Column(db.Integer, nullable=True)

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
    timestamp = db.Column(db.String(50), index=True, default=timestamp)
    # Add device config file in DB
    device_config = db.Column(db.Text, nullable=False)
    # Add device ip DB
    device_ip = db.Column(db.String(50), index=True, nullable=False)
    #
    device_id = db.Column(db.Integer, index=True, nullable=True)
    #
    # device_ip = db.Column(
    #     db.String, db.ForeignKey("devices.device_ip", name="test"), nullable=False
    # )
    # Return format massages from DB

    def __repr__(self):
        return "<Configs %r>" % self.device_ip


class Users(db.Model):
    """
    Class for processing and storing data about user systems
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    email = db.Column(db.String(100), unique=True)
    #
    password = db.Column(db.String(100))
    #
    username = db.Column(db.String(1000))
    #
    role = db.Column(db.String(100))
    #
    auth_method = db.Column(db.String(20))

    def __repr__(self):
        return f"<Users {self.username}>"


class UserRoles(db.Model):
    """
    Users role [user, admin, sadmin]
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    role_name = db.Column(db.String(100))

    # Return format massages from DB
    def __repr__(self):
        return f"User nrole: {self.role_name}"


class DevicesGroup(db.Model):
    """
    Custom field (device groups or site name etc)
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    group_name = db.Column(db.String(100))

    # Return format massages from DB
    def __repr__(self):
        return f"Group name: {self.group_name}"


class GroupPermission(db.Model):
    """
    This table joins two tables:
    1. Table with users
    2. Table with device groups
    This is necessary so that users can see devices only from their groups.
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    user_id = db.Column(
        db.Integer,
    )
    #
    user_group_id = db.Column(
        db.Integer,
    )

    # Return format massages from DB
    def __repr__(self):
        return f"User id: {self.user_id}"


class UserGroup(db.Model):
    """
    Group table for users
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    user_group_name = db.Column(db.String(100))

    # Return format massages from DB
    def __repr__(self):
        return f"User group name: {self.user_group_name}"


class AssociatingDevice(db.Model):
    """
    This table links user groups and devices
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    device_id = db.Column(
        db.Integer,
    )
    #
    user_group_id = db.Column(
        db.Integer,
    )

    # Return format massages from DB
    def __repr__(self):
        return f"User group name: {self.user_group_id}"


class Credentials(db.Model):
    """
    This table links user groups and devices
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    credentials_name = db.Column(db.String(100), index=True, nullable=False)
    credentials_username = db.Column(db.String(100), index=True, nullable=True)
    credentials_password = db.Column(db.String(100), index=True, nullable=True)
    user_group_id = db.Column(db.Integer,)

    # Return format massages from DB
    def __repr__(self):
        return f"User group name: {self.user_group_id}"
