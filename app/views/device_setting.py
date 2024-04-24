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
    Ajax function to check device status
    """
    if request.method == "POST":
        data = request.get_json()
        device_id = data["device_id"]
        user_groups = get_associate_user_group(user_id=session["user_id"])
        device_setting = get_device_setting(device_id=int(device_id))
        return jsonify(
            {
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
