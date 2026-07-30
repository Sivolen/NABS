from app import db
from datetime import datetime, timezone

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
    #
    device_model = db.Column(db.String(100), index=True, nullable=True)
    # Add timestamp in DB
    timestamp = db.Column(db.String(50), default=timestamp)
    #
    connection_status = db.Column(db.String(300), index=True, nullable=True)
    #
    custom_drivers_switch = db.Column(db.Boolean, default=False, nullable=True)
    connection_driver = db.Column(db.String(20), index=True, nullable=True)
    custom_driver = db.Column(db.String(20), index=True, nullable=True)
    #
    group_id = db.Column(db.Integer, nullable=True)
    #
    # ssh_user = db.Column(db.String(100), index=True, nullable=True)
    # ssh_pass = db.Column(db.String(100), index=True, nullable=True)
    ssh_port = db.Column(db.Integer, nullable=True)
    #
    credentials_id = db.Column(db.Integer, nullable=True)
    #
    is_enabled = db.Column(db.Boolean, default=True)

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
    device_config = db.Column(
        db.Text,
        nullable=False,
    )
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
    password = db.Column(db.String(256))
    #
    username = db.Column(db.String(1000))
    #
    role = db.Column(db.String(100))
    #
    auth_method = db.Column(db.String(20))
    #
    send_notifications = db.Column(db.Boolean, default=False)

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
    This table links credentials for devices
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    credentials_name = db.Column(db.String(100), index=True, nullable=False)
    credentials_username = db.Column(db.String(100), index=True, nullable=True)
    credentials_password = db.Column(db.String(100), index=True, nullable=True)
    user_group_id = db.Column(
        db.Integer,
    )

    # Return format massages from DB
    def __repr__(self):
        return f"Credential sname: {self.credentials_name}"


class CustomDrivers(db.Model):
    """
    This table links custom drivers for devices
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # primary keys are required by SQLAlchemy
    #
    drivers_name = db.Column(db.String(100), index=True, nullable=False)
    drivers_vendor = db.Column(db.String(100), index=True, nullable=True)
    drivers_model = db.Column(db.String(100), index=True, nullable=True)
    drivers_platform = db.Column(db.String(100), index=True, nullable=True)
    drivers_commands = db.Column(db.String(255), index=True, nullable=True)

    # Return format massages from DB
    def __repr__(self):
        return f"Drivers name: {self.drivers_name}"


class SchedulerSettings(db.Model):
    """
    Таблица для хранения настроек планировщика задач.
    """

    id = db.Column(db.Integer, primary_key=True)
    # Тип триггера: 'interval' (интервал) или 'cron' (расписание)
    trigger_type = db.Column(db.String(20), default="interval")
    # Параметры для интервального триггера (в секундах)
    interval_seconds = db.Column(db.Integer, default=3600)
    # Cron-выражение для расписания (например, '0 2 * * *' для ежедневного запуска в 2 часа ночи)
    cron_expression = db.Column(db.String(100), default="0 2 * * *")
    # Флаг, включён ли планировщик
    is_enabled = db.Column(db.Boolean, default=False)
    # Временная метка последнего изменения
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<SchedulerSettings trigger_type={self.trigger_type}>"


class SchedulerHeartbeat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    last_seen = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    status = db.Column(db.String(50), default="running")
    next_run_time = db.Column(db.DateTime, nullable=True)


class LoginAttempt(db.Model):
    """
    Tracks failed login attempts per email, to throttle brute-force attempts
    on /login. Stored in the DB (rather than in-process memory) so the limit
    is shared correctly across all gunicorn worker processes.
    """

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), index=True, unique=True, nullable=False)
    failed_count = db.Column(db.Integer, default=0, nullable=False)
    last_attempt_at = db.Column(db.DateTime, default=datetime.utcnow)
    locked_until = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<LoginAttempt email={self.email} failed_count={self.failed_count}>"


class ValidationProfile(db.Model):
    """
    Configuration validation profiles linked to network drivers.
    """

    __tablename__ = "validationprofile"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    driver_vendor = db.Column(db.String(50), nullable=True)  # Maps to connection_driver
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    rules = db.relationship(
        'ValidationRule',
        backref='profile',
        cascade='all, delete-orphan',
        lazy=True
    )
    device_validations = db.relationship(
        'DeviceValidation',
        backref='profile',
        cascade='all, delete-orphan',
        lazy=True
    )

    def __repr__(self):
        return f"<ValidationProfile {self.name}>"


class ValidationRule(db.Model):
    """
    Rules associated with a ValidationProfile.
    """

    __tablename__ = "validationrule"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer, db.ForeignKey("validationprofile.id"), nullable=False
    )
    rule_name = db.Column(db.String(100), nullable=False)
    rule_type = db.Column(db.String(50), nullable=False)  # contains, regex, etc.
    pattern = db.Column(db.Text, nullable=True)  # Pattern string or JSON
    enabled = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)

    results = db.relationship(
        'ValidationResult',
        backref='rule',
        cascade='all, delete-orphan',
        lazy=True
    )

    def __repr__(self):
        return f"<ValidationRule {self.rule_name}>"


class DeviceValidation(db.Model):
    """
    Validation status for a specific device.
    """

    __tablename__ = "devicevalidation"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, nullable=False)  # Reference to Devices.id
    profile_id = db.Column(
        db.Integer, db.ForeignKey("validationprofile.id"), nullable=True
    )
    status = db.Column(
        db.String(20), default="pending"
    )  # pending, passed, failed, error
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    results = db.relationship(
        'ValidationResult',
        backref='device_validation',
        cascade='all, delete-orphan',
        lazy=True
    )

    def __repr__(self):
        return f"<DeviceValidation device_id={self.device_id} status={self.status}>"


class ValidationResult(db.Model):
    """
    Result of a single rule execution within a DeviceValidation record.
    """

    __tablename__ = "validationresult"

    id = db.Column(db.Integer, primary_key=True)
    device_validation_id = db.Column(
        db.Integer, db.ForeignKey("devicevalidation.id"), nullable=False
    )
    rule_id = db.Column(db.Integer, db.ForeignKey("validationrule.id"), nullable=False)
    rule_name = db.Column(db.String(100), nullable=True)
    passed = db.Column(db.Boolean, nullable=True)  # Null if not checked yet
    message = db.Column(db.Text, nullable=True)
    checked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ValidationResult rule={self.rule_name} passed={self.passed}>"


# Add new fields to Devices model
Devices.validation_profile_id = db.Column(db.Integer, nullable=True)
Devices.validation_enabled = db.Column(db.Boolean, default=True)
Devices.validation_disabled_by = db.Column(db.String(100), nullable=True)
Devices.validation_disabled_date = db.Column(db.DateTime, nullable=True)
Devices.validation_disabled_reason = db.Column(db.String(500), nullable=True)
