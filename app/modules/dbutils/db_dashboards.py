from sqlalchemy import text
from app import db, logger

def get_devices_count():
    """
    This function needs to get allowed credentials for a user
    """
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
                GROUP BY category
                
                UNION
                
                SELECT 
                  'Total' AS category, 
                  COUNT(*) AS count 
                FROM devices; 
            """
        )
        request_data = db.session.execute(slq_request).fetchall()
        request_dict = {}
        request_dict.update({i[0]: i[1] for i in request_data})
        return request_dict
        # return [
        #     {
        #         "html_element_id": html_element_id,
        #         "config_id": data.id,
        #         "device_id": data.device_id,
        #         "device_ip": data.device_ip,
        #         "timestamp": data.timestamp,
        #         "config_snippet": data.config_snippet.replace("!", "").splitlines(),
        #
        # }
        #     for html_element_id, data in enumerate(request_data, start=1)
        # ]
    except Exception as get_sql_error:
        # If an error occurs as a result of writing to the DB,
        # then rollback the DB and write a message to the log
        logger.info(f"Search data on config error {get_sql_error}")
