from flask import (
    request,
    jsonify,
    session,
)
from app.modules.crypto import decrypt
from app.modules.dbutils.db_credentials import get_credentials
# get_all_credentials
from app.modules.dbutils.db_users_permission import get_associate_user_group
# update_associate_device_group,
from app.modules.dbutils.db_user_rights import check_user_role_block
from app.modules.auth.auth_users_ldap import check_auth
from config import TOKEN


@check_auth
@check_user_role_block
def get_credentials_data():
    """
    Ajax function to check device status
    """
    if request.method == "POST":
        # Render template if get request

        user_groups = get_associate_user_group(user_id=session["user_id"])

        data = request.get_json()
        credentials_id = data["credentials_id"]
        credentials_profile = get_credentials(credentials_id=int(credentials_id))
        # device_setting = get_device_setting(device_id=device_id)
        if credentials_profile["credentials_password"] is not None:
            ssh_pass = decrypt(
                ssh_pass=credentials_profile["credentials_password"], key=TOKEN
            )
        else:
            ssh_pass = "The password is not set"
        return jsonify(
            {
                "credentials_name": credentials_profile["credentials_name"],
                "credentials_username": credentials_profile["credentials_username"],
                "credentials_password": ssh_pass,
                "user_groups": user_groups,
                "user_group": credentials_profile["credentials_user_group"],
            }
        )