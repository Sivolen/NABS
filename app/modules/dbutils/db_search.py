from sqlalchemy import text
from app import db, logger


def search_in_db(request_data: str , user_id: int):
    """
    This function needs to get allowed credentials for a user
    """
    if not isinstance(request_data, str) and request_data is None:
        logger.info(f"Request data must be a string")
        return False
    if not isinstance(user_id, int) and user_id is None:
        logger.info(f"User id must be a integer")
        return False
    try:
        slq_request = text(
            # "SELECT id, "
            # "device_id,"
            # "device_ip, "
            # "timestamp, "
            # "substring(device_config, greatest(strpos(device_config, :search) - 35, 1), least(length(device_config), strpos(device_config, :search) + 35) - greatest(strpos(device_config, :search) - 35, 1) + 1) AS config_snippet "
            # "FROM configs "
            # "WHERE device_config LIKE '%' || :search  || '%' "
            # "group by device_ip, configs.id "
            # "ORDER BY timestamp DESC;"
            "SELECT configs.id, "
            "device_ip, "
            "configs.device_id, "
            "timestamp, "
            "substring(device_config, greatest(strpos(device_config, :search) - 50, 1), least(length(device_config), strpos(device_config, :search) + 50) - greatest(strpos(device_config, :search) - 50, 1) + 1) AS config_snippet "
            "FROM configs "
            "LEFT JOIN associating_device ON associating_device.device_id = configs.device_id "
            "LEFT JOIN group_permission ON group_permission.user_group_id = associating_device.user_group_id "
            "WHERE group_permission.user_id = :user_id AND device_config  LIKE '%' || CAST(:search AS TEXT) || '%' "
            "GROUP BY configs.device_id, configs.id "
            "ORDER BY timestamp DESC;"
        )
        parameters = {"search": request_data, "user_id": user_id,}
        request_data = db.session.execute(slq_request, parameters).fetchall()
        return [
            {
                "html_element_id": html_element_id,
                "config_id": data.id,
                "device_id": data.device_id,
                "device_ip": data.device_ip,
                "timestamp": data.timestamp,
                "config_snippet": data.config_snippet.replace("!", "").splitlines(),

        }
            for html_element_id, data in enumerate(request_data, start=1)
        ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Search data on config error {get_sql_error}")