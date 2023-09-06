from flask import render_template, session
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_devices import get_allowed_devices_by_right
from app.modules.log_parser import log_parser, logs_viewer_by_rights


@check_auth
def reports():
    """
    function to be view the logs
    """
    reports_menu_active = True
    return render_template(
        "reports.html",
        reports_menu_active=reports_menu_active,
        reports=logs_viewer_by_rights(user_id=int(session["user_id"])),
    )
