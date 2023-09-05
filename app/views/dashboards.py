from flask import (
    render_template,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_dashboards import get_devices_count


@check_auth
def dashboards():
    dashboard_menu_active: bool = True
    return render_template(
        "dashboards.html",
        dashboard_menu_active=dashboard_menu_active,
        devices_count=get_devices_count(),
    )
