from flask import (
    render_template,
    request,
    flash,
    session,
    redirect,
)
from app import app
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    check_if_previous_configuration_exists,
    get_device_id,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_search import search_in_db

@check_auth
def search():
    """
    Old function to be changed for full configuration search
    """
    search_menu_active = True
    if request.method == "POST" and request.form.get("search_input"):
        request_data = request.form.get("search_input")
        response_data = search_in_db(request_data=str(request_data), user_id=int(session["user_id"]))
        return render_template("search.html", devices_menu_active=search_menu_active, response_data=response_data)

    return render_template("search.html", devices_menu_active=search_menu_active,)