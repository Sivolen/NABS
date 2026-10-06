from flask import (
    request,
    jsonify,
    session,
)
from app.modules.dbutils.db_credentials import get_credentials

# get_all_credentials
from app.modules.dbutils.db_users_permission import get_associate_user_group

# update_associate_device_group,
from app.modules.dbutils.db_user_rights import (
    check_admin_or_above_block,
    is_group_allowed_for_user,
)
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_admin_or_above_block
def get_credentials_data():
    """
    Ajax function to check device status
    """
    if request.method == "POST":
        # Render template if get request

        data = request.get_json(silent=True) or {}
        credentials_id = data.get("credentials_id")
        if credentials_id is None:
            return (
                jsonify({"status": "error", "message": "credentials_id is required"}),
                400,
            )

        try:
            credentials_id = int(credentials_id)
        except (TypeError, ValueError):
            return (
                jsonify({"status": "error", "message": "Invalid credentials_id"}),
                400,
            )

        credentials_profile = get_credentials(credentials_id=credentials_id)
        if not credentials_profile:
            return jsonify({"status": "error", "message": "Credentials not found"}), 404

        # Access control: only sadmin, or a user/admin whose group membership
        # includes this credentials profile's group, may read it (never its password).
        if not is_group_allowed_for_user(
            credentials_profile["credentials_user_group"], session
        ):
            return jsonify({"status": "error", "message": "Access denied"}), 403

        user_groups = get_associate_user_group(user_id=session["user_id"])

        # The password - neither plain nor encrypted - is NEVER sent to the browser:
        # the edit form shows an empty field, and an empty field keeps the password.
        return jsonify(
            {
                "credentials_name": credentials_profile["credentials_name"],
                "credentials_username": credentials_profile["credentials_username"],
                "has_password": credentials_profile["credentials_password"] is not None,
                "user_groups": user_groups,
                "user_group": credentials_profile["credentials_user_group"],
            }
        )
    return jsonify({"status": "error", "message": "Method not allowed"}), 405
