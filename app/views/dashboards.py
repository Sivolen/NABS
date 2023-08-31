from flask import (
    render_template,
)
from app import app
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
def dashboards():
    dashboard_menu_active: bool = True
    return render_template(
        "dashboards.html",
        dashboard_menu_active=dashboard_menu_active,
    )