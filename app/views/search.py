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

@check_auth
def search():
    """
    Old function to be changed for full configuration search
    """
    navigation = True
    if request.method == "GET":
        return render_template("index.html", navigation=navigation)
    if request.method == "POST":
        if request.form.get("search_input"):
            ipaddress = request.form.get("search_input")
            device_id = get_device_id(ipaddress=ipaddress)["id"]
            app.logger.info(f'User {session["user"]} search device {ipaddress}')
            check_last_config = get_last_config_for_device(device_id=device_id)

            if check_last_config is None:
                flash("Device not found, check the entered ipaddress", "warning")
                return render_template(
                    "index.html", ipaddress=ipaddress, navigation=navigation
                )

            check_previous_config = check_if_previous_configuration_exists(
                device_id=device_id
            )

            if check_previous_config:
                return redirect(f"/diff_page/{ipaddress}")

            if not check_previous_config:
                flash("This device has no previous configuration ", "info")
                return redirect(f"/config_page/{ipaddress}")