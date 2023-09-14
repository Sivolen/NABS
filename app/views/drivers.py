from flask import render_template

from app.modules.auth.auth_users_ldap import check_auth


@check_auth
def drivers():
    """
    Function for search
    """
    drivers_menu_active: bool = True
    settings_menu_active: bool = True
    #
    return render_template(
        "drivers.html",
        drivers_menu_active=drivers_menu_active,
        settings_menu_active=settings_menu_active,

    )
