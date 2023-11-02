from sqlalchemy import text
from app import db, logger
from app.models import CustomDrivers


def add_driver(
    drivers_name: str,
    drivers_vendor: str,
    drivers_model: str,
    drivers_commands: str,
) -> bool:
    """
    This function is needed to add driver param on db
    Parm:
        name: str
        vendor: str
        model: str
        drivers_commands: str
    return:
        bool
    """
    try:
        data = CustomDrivers(
            drivers_name=drivers_name,
            drivers_vendor=drivers_vendor,
            drivers_model=drivers_model,
            drivers_commands=drivers_commands,
        )
        # Sending data in BD
        db.session.add(data)
        # Apply changing
        db.session.commit()
        return True
    except Exception as update_db_error:
        db.session.rollback()
        logger.info(f"Add driver {drivers_name} error {update_db_error}")
        return False


def get_all_drivers() -> list:
    """
    This function return device id
    """
    """
     The function gets env for all devices to which the user has access from the database
     return:
     Devices env dict
     Get all Roles
     """
    try:
        slq_request = text(
            """
            select 
            id as custom_drivers_id, 
            drivers_name as drivers_name, 
            drivers_vendor as drivers_vendor, 
            drivers_model as drivers_model, 
            drivers_commands as drivers_commands 
            from Custom_Drivers 
            """
        )
        devices_data = db.session.execute(slq_request).fetchall()
        return [
            {
                "html_elements_count": drivers_count,
                "custom_drivers_id": data[0],
                "devices_name": data[1],
                "drivers_vendor": data[2],
                "drivers_model": data[3],
                "drivers_commands": data[4].split(",") if data[4] else [],
            }
            for drivers_count, data in enumerate(devices_data, start=1)
        ]

    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Getting associate error {get_sql_error}")


def get_driver_settings(custom_drivers_id: int) -> dict or None:
    """
    This function needs to get driver setting for ajax function
    """
    if not isinstance(custom_drivers_id, int) or custom_drivers_id is None:
        logger.info(
            f"Getting driver settings error, custom_drivers_id must be an integer"
        )
        return None
    try:
        slq_request = text(
            """
            select 
            id as custom_drivers_id, 
            drivers_name as drivers_name, 
            drivers_vendor as drivers_vendor,  
            drivers_model as drivers_model, 
            drivers_commands as drivers_commands  
            from Custom_Drivers 
            where id = :custom_drivers_id
            """
        )
        parameters = {"custom_drivers_id": custom_drivers_id}
        driver_data = db.session.execute(slq_request, parameters).fetchall()[0]
        if not driver_data:
            logger.info(f"Getting driver settings error, check your db settings")
            return None
        return {
            "custom_drivers_id": driver_data[0] if driver_data[0] else None,
            "drivers_name": driver_data[1] if driver_data[1] else None,
            "drivers_vendor": driver_data[2] if driver_data[2] else None,
            "drivers_model": driver_data[3] if driver_data[3] else None,
            "drivers_commands": driver_data[4] if driver_data[4] else None,
        }
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Getting driver settings error {get_sql_error}")
        return None


def update_driver(
    custom_drivers_id: int,
    drivers_name: str,
    drivers_vendor: str,
    drivers_model: str,
    drivers_commands: str,
) -> bool or None:
    """
    This function update a credentials to the DB
    parm:
        custom_drivers_id: int
        drivers_name: str
        drivers_vendor: str
        drivers_model: str
        drivers_commands: str
    return:
        bool
    """
    if not isinstance(custom_drivers_id, int) or custom_drivers_id is None:
        logger.info(
            f"Update driver settings error, custom_drivers_id must be an integer"
        )
        return None
    try:
        # Getting device data from db
        driver_data = (
            db.session.query(CustomDrivers).filter_by(id=int(custom_drivers_id)).first()
        )
        if driver_data.drivers_name != drivers_name:
            driver_data.drivers_name = drivers_name
        if driver_data.drivers_vendor != drivers_vendor:
            driver_data.drivers_vendor = drivers_vendor
        if driver_data.drivers_model != drivers_model:
            driver_data.drivers_model = drivers_model
        if driver_data.drivers_commands != drivers_commands:
            driver_data.drivers_commands = drivers_commands

        # Apply changing
        db.session.commit()
        return True

    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update driver error {update_sql_error}")
        db.session.rollback()
        return False


def delete_custom_driver(custom_driver_id: int) -> bool:
    """
    This function is needed to delete command from db
    Parm:
        id: str
    return:
        bool
    """
    if not isinstance(custom_driver_id, int) or custom_driver_id is None:
        logger.info(
            f"Deleting driver settings error, custom_driver_id must be an integer"
        )
        return False
    try:
        CustomDrivers.query.filter_by(id=int(custom_driver_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_error:
        db.session.rollback()
        logger.info(f"Delete driver id {custom_driver_id} error {delete_device_error}")
        return False
