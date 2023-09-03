from sqlalchemy import text
from app import db, logger


def search_in_db(request_data: str):
    """
    This function needs to get allowed credentials for a user
    """
    if isinstance(request_data, str) and request_data is not None:
        try:
            slq_request = text(
                "SELECT id, "
                "device_id,"
                "device_ip, "
                "timestamp, "
                "substring(device_config, greatest(strpos(device_config, :search) - 35, 1), least(length(device_config), strpos(device_config, :search) + 35) - greatest(strpos(device_config, :search) - 35, 1) + 1) AS config_snippet "
                "FROM configs "
                "WHERE device_config LIKE '%' || :search  || '%' "
                "group by device_ip, configs.id "
                "ORDER BY timestamp DESC;"
            )
            parameters = {"search": request_data}
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
            logger.info(f"getting allowed credentials error {get_sql_error}")