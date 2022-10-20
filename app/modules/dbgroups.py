from app.models import Devices, DevicesGroup
from app import db, logger


def add_device_group(group_name: str) -> bool:
    """
    This function adds a new device group to the database.    Need to parm:
    group_name: str
    return:
        None
    """
    # We form a request to the database and pass the IP address and device environment
    device_group = DevicesGroup(
        group_name=group_name,
    )
    try:
        # Sending data in BD
        db.session.add(device_group)
        # Committing changes
        db.session.commit()
        return True
    except Exception as write_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Adds device group error {write_sql_error}")
        db.session.rollback()
        return False


def del_device_group(group_id: int) -> bool:
    """
    This function is needed to delete device group from db
    Parm:
        id: int
    return:
        bool
    """
    try:
        DevicesGroup.query.filter_by(id=int(group_id)).delete()
        db.session.commit()
        return True
    except Exception as delete_device_group_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        db.session.rollback()
        logger.info(
            f"Delete device group id {group_id} error {delete_device_group_error}"
        )
        return False


def update_device_group(group_id: int, group_name: str) -> bool:
    """
    This function update a device group to the DB
    parm:
        group_id: int
        group_name: str
    return:
        bool
    """
    try:
        # Getting device data from db
        data = db.session.query(Devices).filter_by(id=int(group_id)).first()
        if data.group_name != group_name:
            data.group_name = group_name
        # Apply changing
        db.session.commit()
        return True

    except Exception as update_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Update device group error {update_sql_error}")
        db.session.rollback()
        return False


def get_all_devices_group() -> list[dict]:
    """
    This function return all device groups
    """
    groups = DevicesGroup.query.order_by(DevicesGroup.id)
    return [
        {
            "html_element_id": html_element_id,
            "group_id": group.id,
            "group_name": group.group_name,
        }
        for html_element_id, group in enumerate(groups, start=1)
    ]


# def get_device_group_for_device(device_id: int):
#     device_data = (
#         DevicesGroup.query.with_entities(DevicesGroup.id, DevicesGroup.group_name).filter_by(device_id=device_id)
#     )
#     pass
