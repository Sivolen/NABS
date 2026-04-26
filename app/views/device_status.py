import traceback
from datetime import datetime
from flask import (
    request,
    jsonify,
)

from app import logger
from app.modules.backuper import run_backup_config_on_db
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_devices import get_device_is_enabled, get_device_id


# Ajax function to check device status
@check_auth
def device_status():
    if request.method != "POST":
        return jsonify({"status": "error", "message": "Method not allowed"}), 405

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": False, "error": "No data provided"}), 400

        device_ip = data.get("device")
        if not device_ip:
            return jsonify({"status": False, "error": "Device IP missing"}), 400

        # Получаем device_id и is_enabled
        device_id_row = get_device_id(ipaddress=device_ip)
        if not device_id_row:
            return jsonify({"status": False, "error": "Device not found"}), 404
        device_id = device_id_row[0]
        is_enabled = get_device_is_enabled(device_id)

        if not is_enabled:
            return jsonify(
                {
                    "status": True,
                    "device_id": device_id,
                    "device_ip": device_ip,
                    "vendor": "Disabled",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "last_changed": None,
                    "connection_status": "Device disabled",
                    "is_enabled": False,
                }
            )

        # Вызов бэкапа
        result_dict = run_backup_config_on_db(data)
        if result_dict is None:
            return jsonify({"status": False, "error": "Backup returned None"}), 500

        return jsonify(
            {
                "status": True,
                "device_id": result_dict.get("device_id"),
                "device_ip": result_dict.get("device_ip"),
                "vendor": result_dict.get("vendor"),
                "timestamp": result_dict.get("timestamp"),
                "last_changed": result_dict.get("last_changed"),
                "connection_status": str(result_dict.get("connection_status")),
                "is_enabled": True,
            }
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Device status error: {error_msg}\n{traceback.format_exc()}")
        return jsonify({"status": False, "error": f"Backup error: {error_msg}"}), 200
