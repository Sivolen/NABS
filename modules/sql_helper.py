from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from pathlib import Path
from config import token

app = Flask(__name__)
app.config["SECRET_KEY"] = token
app.config.update(SESSION_COOKIE_SAMESITE="Strict")
app.config[
    "SQLALCHEMY_DATABASE_URI"
] = f"sqlite:///{Path(__file__).parent.parent}/devices.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# current date and time
now = datetime.now()
timestamp = now.strftime("%Y-%m-%d %H:%M")


class Devices(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    device_ip = db.Column(db.Integer, index=True, nullable=False)
    device_hostname = db.Column(db.String(50), index=True, nullable=True)
    # device_env = db.Column(db.String(100), index=True, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now())

    def __repr__(self):
        return "<Devices %r>" % self.device_ip


class Configs(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now())
    device_config = db.Column(db.Text, nullable=False)
    device_ip = db.Column(db.Integer, db.ForeignKey("devices.device_ip"))

    def __repr__(self):
        return "<Configs %r>" % self.device_ip


# db.create_all()

# device = Devices(device_hostname="yzh-det1b-1f-asw01-sw01", device_ip="10.0.0.12")
# #
#
# db.session.add(device)
# db.session.commit()
#
# device = Devices(device_hostname="asw01", device_ip="10.0.1.1", device_config="122222222222222222222")
#
#
# db.session.add(device)
# db.session.commit()
def get_last_config_for_device(ipaddress: str) -> dict or None:
    try:
        data = (
            Configs.query.order_by(Configs.timestamp.desc())
            .filter_by(device_ip=ipaddress)
            .first()
        )
        db_last_config = data.device_config
        db_last_timestamp = data.timestamp
        return {"last_config": db_last_config, "timestamp": db_last_timestamp}
    except:
        return None


def get_all_cfg_for_ipaddress(ipaddress: str) -> list or None:
    try:
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress
        )
        return [db_timestamp.timestamp for db_timestamp in data[1:]]
    except:
        return None


def get_previous_config(ipaddress: str, db_timestamp: str) -> str or None:
    try:
        data = Configs.query.order_by(Configs.timestamp.desc()).filter_by(
            device_ip=ipaddress, timestamp=db_timestamp
        )
        return data[0].device_config
    except:
        return None


def write_cfg_on_db(ipaddress: str, config: str) -> None:
    config = Configs(device_ip=ipaddress, device_config=config)
    try:
        db.session.add(config)
        db.session.commit()
    except Exception as write_sql_error:
        print(write_sql_error)
        db.session.rollback()


# def get_data_on_db(ipaddress):
#     device = Devices.query.order_by(Devices.timestamp.desc()).filter_by(device_ip=ipaddress).first()
#     print(device)
#     last_config = Configs.query.order_by(Configs.timestamp.desc()).filter_by(device_ip=ipaddress).first()
#     print(last_config.device_config)
#     # for device in last_config:
#     #     print(device)
#     return device

# if __name__ == "__main__":
# # get_data_on_db(ipaddress="10.255.100.81")
# # last_config = get_previous_config("10.255.100.1", "2022-02-17 06:24:57.635107")
# # print(last_config)
#     write_cfg_on_db(ipaddress="10.2.10.1", config="device")
# # print(get_last_config_for_device("10.255.101.85"))
