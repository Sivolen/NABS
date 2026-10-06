from flask import request, jsonify, session

from app.modules.dbutils.db_utils import get_previous_config, get_last_config_for_device
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.access import can_access_device, parse_id


# Ajax function get previous configs for device
@check_auth
def previous_config():
    """
    Ajax function get previous configs for device
    """
    if request.method == "POST":
        previous_config_data = request.get_json(silent=True) or {}
        device_id = parse_id(previous_config_data.get("device_id"))
        previous_timestamp = previous_config_data.get("date")
        if device_id is None or previous_timestamp is None:
            return jsonify({"status": "error", "message": "Invalid request"}), 400
        if not can_access_device(session, device_id):
            return jsonify({"status": "error", "message": "Access denied"}), 403
        previous_config_dict = get_previous_config(
            device_id=device_id, db_timestamp=previous_timestamp
        )
        if previous_config_dict is None:
            result = "none"
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": None,
                }
            )

        result = "ok"
        last_config_dict: dict = get_last_config_for_device(device_id=device_id)
        return jsonify(
            {
                "status": result,
                "config_id": previous_config_dict["id"],
                "last_config_dict": last_config_dict["last_config"],
                "previous_config_file": previous_config_dict["device_config"],
                "previous_config_file_split": previous_config_dict[
                    "device_config"
                ].splitlines(),
                "timestamp": previous_config_dict["timestamp"],
            }
        )
    return jsonify({"status": "error", "message": "Method not allowed"}), 405
