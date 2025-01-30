from flask import (
    request,
    jsonify,
    session,
)

from app.modules.dbutils.db_credentials import get_allowed_credentials
from app.modules.dbutils.db_devices import get_device_setting
from app.modules.dbutils.db_drivers import get_all_drivers
from app.modules.dbutils.db_groups import get_all_devices_group
from app.modules.dbutils.db_users_permission import get_associate_user_group
from app.modules.dbutils.db_user_rights import check_user_role_block
from app.modules.auth.auth_users_ldap import check_auth

from config import drivers


@check_auth
@check_user_role_block
def device_settings():
    """
    AJAX endpoint for retrieving device settings and related information

    Expected JSON payload:
    {
        "device_id": int
    }

    Returns:
    {
        "device_info": {
            "hostname": str,
            "ip": str,
            "driver": str,
            "ssh_port": int,
            "enabled": bool
        },
        "groups": {
            "device_group": dict,
            "user_groups": list,
            "available_groups": list
        },
        "credentials": {
            "current": int,
            "available": list
        },
        "drivers": {
            "standard": list,
            "custom": list
        }
    }
    """
    if request.method == "POST":
        data = request.get_json()
        # Input data validation
        if not data or "device_id" not in data:
            raise ValueError("Invalid request payload")

        device_id = data["device_id"]
        user_id = session["user_id"]

        try:
            device_id = int(device_id)
        except (ValueError, TypeError):
            raise ValueError("Invalid device ID format")

        user_groups = get_associate_user_group(user_id=user_id)
        device_setting = get_device_setting(device_id=device_id)
        return jsonify(
            {
                "device_group_id": device_setting["device_group_id"],
                "device_group": device_setting["device_group"],
                "device_hostname": device_setting["device_hostname"],
                "device_ipaddress": device_setting["device_ip"],
                "device_driver": device_setting["connection_driver"],
                "ssh_port": device_setting["ssh_port"],
                "user_group": device_setting["user_group"],
                "credentials_id": device_setting["credentials_id"],
                "is_enabled": device_setting["is_enabled"],
                "drivers": drivers,
                "custom_drivers": get_all_drivers(),
                "devices_group": get_all_devices_group(),
                "user_groups": user_groups,
                "credentials_profiles": get_allowed_credentials(
                    user_id=session["user_id"]
                ),
            }
        )
