from flask import (
    render_template,
    session,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_dashboards import (
    get_devices_count,
    get_models_count,
    get_configs_count,
    get_error_connections_limit,
    get_statistic,
)


@check_auth
def dashboards():
    dashboard_menu_active: bool = True
    return render_template(
        "dashboards.html",
        dashboard_menu_active=dashboard_menu_active,
        devices_count=get_devices_count(user_id=session["user_id"]),
        models_count=get_models_count(user_id=session["user_id"]),
        configs_count=get_configs_count(user_id=session["user_id"]),
        error_connections=get_error_connections_limit(user_id=session["user_id"]),
        year_statistic=get_statistic(user_id=session["user_id"]),
    )
