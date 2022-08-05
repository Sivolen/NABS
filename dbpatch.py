# if you NABS < 1.3 you need starts this patch after update
#
from app.models import Configs, Devices
from app import db


def modyfydb():
    devices = Devices.query.with_entities(
        Devices.id,
        Devices.device_ip,
    )
    for device in devices:

        try:
            configs = db.session.query(Configs).filter_by(device_ip=device.device_ip)
            for config in configs:

                print(config.device_ip)
                config.device_id = int(device.id)
                print(config.device_id)

                db.session.commit()

                print(f"{device.device_ip} Done {device.id}")
        except:
            db.session.rollback()
            print(f"{device.device_ip} error")


def checkdb():
    devices = Devices.query.with_entities(
        Devices.id,
        Devices.device_ip,
    )
    for device in devices:
        configs = Configs.query.with_entities(Configs.id, Configs.device_ip, Configs.device_id).filter_by(
            device_ip=device.device_ip)
        for config in configs:
            print(config)
            print(config.device_id)


def main():
    modyfydb()
    checkdb()


if __name__ == "__main__":
    main()
