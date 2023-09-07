from sqlalchemy import text
from app import db, logger


def get_devices_count(user_id: int) -> dict or bool:
    """
    This function needs to get allowed device count
    """
    if not isinstance(user_id, int) or user_id is None:
        logger.info(
            f"Get devices count for {user_id} error, device id is not a integer"
        )
        return False
    try:
        slq_request = text(
            """
                SELECT 
                  CASE 
                    WHEN device_vendor IS NULL THEN 'Unknown' 
                    ELSE device_vendor 
                  END AS category, 
                  COUNT(*) AS count 
                FROM devices 
                left join associating_device on associating_device.device_id = devices.id 
                left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id 
                where group_permission.user_id = :user_id 
                GROUP BY category
                
                UNION
                
                SELECT 
                  'Total' AS category, 
                  COUNT(*) AS count 
                FROM devices 
                left join associating_device on associating_device.device_id = devices.id 
                left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id 
                where group_permission.user_id = :user_id 
            """
        )
        parameters = {"user_id": user_id}
        request_data = db.session.execute(slq_request, parameters).fetchall()
        request_dict = {}
        request_dict.update({i[0]: i[1] for i in request_data})
        return request_dict
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Get device count on devices error {get_sql_error}")


def get_models_count(user_id: int) -> dict or bool:
    """
    This function needs to get allowed models count
    """
    if not isinstance(user_id, int) or user_id is None:
        logger.info(f"Get models count for {user_id} error, user id is not a integer")
        return False
    try:
        slq_request = text(
            """
                SELECT 
                  CASE 
                    WHEN device_model IS NULL THEN 'unknown' 
                    ELSE device_model 
                  END AS category, 
                  COUNT(*) AS count 
                FROM devices 
                left join associating_device on associating_device.device_id = devices.id 
                left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id 
                where group_permission.user_id = :user_id 
                GROUP BY category
                ORDER BY count DESC
                LIMIT 10; 
            """
        )
        parameters = {"user_id": user_id}
        request_data = db.session.execute(slq_request, parameters).fetchall()
        request_dict = {}
        request_dict.update({i[0]: i[1] for i in request_data})
        return request_dict
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Get model count on devices error {get_sql_error}")


def get_configs_count(user_id: int) -> dict or bool:
    """
    This function needs to get allowed config count
    """
    if not isinstance(user_id, int) or user_id is None:
        logger.info(f"Get config count for {user_id} error, user id is not a integer")
        return False
    try:
        slq_request = text(
            """
                SELECT 
                  CASE 
                    WHEN device_hostname IS NULL THEN configs.device_ip
                    ELSE  device_hostname 
                  END AS category, 
                  COUNT(*) AS count 
                FROM configs 
                left join associating_device on associating_device.device_id = configs.device_id 
                left join group_permission on group_permission.user_group_id = Associating_Device.user_group_id
                left join devices on devices.id = configs.device_id 
                where group_permission.user_id = :user_id
                GROUP BY category
                ORDER BY count DESC
                LIMIT 10; 
            """
        )
        parameters = {"user_id": user_id}
        request_data = db.session.execute(slq_request, parameters).fetchall()
        request_dict = {}
        request_dict.update({i[0]: i[1] for i in request_data})
        return request_dict
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Get configs count on devices error {get_sql_error}")


def get_error_connections_limit(user_id: int) -> list or bool:
    """
    This function needs to get last 10 error connection
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
            limit 10;
            """
        )
        parameters = {"user_id": user_id}
        request_data = db.session.execute(slq_request, parameters).fetchall()
        return [
            {
                "html_element_count": html_element_count,
                "connection_status": i["connection_status"],
                "device_ip": i["device_ip"],
                "device_hostname": i["device_hostname"],
                "device_vendor": i["device_vendor"],
                "timestamp": i["timestamp"],
            }
            for html_element_count, i in enumerate(request_data, start=1)
        ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Get error connection on devices error {get_sql_error}")
