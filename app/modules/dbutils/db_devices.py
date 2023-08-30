from sqlalchemy import text

from app.models import Configs, Devices, AssociatingDevice
from app.modules.crypto import encrypt
from config import TOKEN
from app import db, logger


def update_device_credentials(
    device_id: int,
    credentials_id: int,
) -> bool:
    """
    This function is needed to update device param on db
    Parm:
        device_id: int
        credentials_id: int
    return:
        bool
    """
    try:
        if not isinstance(device_id, int) or device_id is None:
            logger.info(
                f"Update device credentials {device_id} error, device id is not a integer"
            )
            return False

        if not isinstance(credentials_id, int) or credentials_id is None:
            logger.info(
                f"Update device credentials {device_id} error, credentials id is not a integer"
            )
            return False

        device_data = db.session.query(Devices).filter_by(id=int(device_id)).first()
        print(device_data.credentials_id)
        print(credentials_id)
        if device_data.credentials_id != credentials_id:
            device_data.credentials_id = credentials_id

        # Apply changing
        db.session.commit()
        return True
    except Exception as update_db_error:
        db.session.rollback()
        logger.info(f"Update device {device_id} error {update_db_error}")
        return False


def get_allowed_devices_by_right(user_id: int) -> list:
    """
    The function gets env for all devices to which the user has access from the database
    return:
    Devices env dict
    Get all Roles
    """
    if isinstance(user_id, int) and user_id is not None:
        try:
            slq_request = text(
                """
                select Devices.id,  
                Devices.device_ip, 
                Devices.device_hostname, 
                Devices.credentials_id 
                from Associating_Device 
                left join Devices on Devices.id = Associating_Device.device_id  
                left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id 
                where group_permission.user_id = :user_id group by Devices.id
                """
            )
            parameters = {"user_id": user_id}
            devices_data = db.session.execute(slq_request, parameters).fetchall()
            return [
                {
                    "html_element_id": html_element_id,
                    "device_id": device["id"],
                    "device_ip": device["device_ip"],
                    "device_hostname": device["device_hostname"],
                    "credentials_id": device["credentials_id"],
                }
                for html_element_id, device in enumerate(devices_data, start=1)
            ]
        except Exception as get_sql_error:
            # If an error occurs as a result of writing to the DB,
            # then rollback the DB and write a message to the log
            logger.info(f"getting associate error {get_sql_error}")
