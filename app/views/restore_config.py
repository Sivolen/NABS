from flask import (
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_user_rights import check_user_role_block

RESTORE_UNAVAILABLE = "Restoring a configuration is not available in this version"


# Restoring a configuration on a device is NOT implemented (a separate project). The
# route stays so that a direct request gets a clear answer instead of an HTTP 500: it
# reads nothing from the request, touches neither the database nor a device, and changes
# nothing.
@check_auth
@check_user_role_block
def restore_config():
    if request.is_json or request.accept_mimetypes.best == "application/json":
        return jsonify({"status": "error", "message": RESTORE_UNAVAILABLE}), 501
    flash(RESTORE_UNAVAILABLE, "info")
    return redirect(url_for("devices"))
