from flask import render_template, session
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_reports import get_error_connections


@check_auth
def reports():
    """
    function to be view the logs
    """
    reports_menu_active = True
    return render_template(
        "reports.html",
        reports_menu_active=reports_menu_active,
        reports=get_error_connections(user_id=int(session["user_id"])),
    )
