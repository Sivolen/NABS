from sqlalchemy import text
from app import db, logger


def get_error_connections(user_id: int) -> list or bool:
    """
    This function needs to get error connection
    """
    if not isinstance(user_id, int) or user_id is None:
        logger.info(
            f"Get error connection for {user_id} error, user id is not a integer"
        )
        return False
    try:
        slq_request = text(
            """
            SELECT connection_status, 
                device_id, 
                device_ip,
                device_hostname,  
                device_vendor, 
                timestamp 
            FROM Associating_Device 
            LEFT JOIN Devices ON Devices.id = Associating_Device.device_id 
            LEFT JOIN group_permission ON group_permission.user_group_id = Associating_Device.user_group_id 
            WHERE group_permission.user_id = :user_id AND Devices.connection_status <> 'Ok' 
            ORDER BY timestamp desc 
            """
        )
        parameters = {"user_id": user_id}
        request_data = db.session.execute(slq_request, parameters).fetchall()
        return [
            {
                "html_element_count": html_element_count,
                "connection_status": i[0],
                "device_ip": i[2],
                "device_hostname": i[3],
                "device_vendor": i[4],
                "timestamp": i[5],
            }
            for html_element_count, i in enumerate(request_data, start=1)
        ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Get error connection on devices error {get_sql_error}")
