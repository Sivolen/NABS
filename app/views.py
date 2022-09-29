from flask import (
    render_template,
    request,
    flash,
    jsonify,
    session,
    url_for,
    redirect,
)

from app import app
from app.modules.backuper import backup_config_on_db
from app.modules.dbutils import (
    get_last_config_for_device,
    get_all_cfg_timestamp_for_device,
    get_previous_config,
    check_if_previous_configuration_exists,
    get_all_cfg_timestamp_for_config_page,
    add_device,
    delete_device,
    update_device,
    delete_config,
    get_last_env_for_device,
    get_device_id,
    get_devices_env,
)

from app.utils import check_ip

from app import logger

from app.modules.auth_users import AuthUsers

from app.modules.auth_ldap import LdapFlask, check_auth
from config import local_login


@app.errorhandler(404)
@check_auth
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template("404.html"), 404


# Home page and search devices
@app.route("/search", methods=["POST", "GET"])
@check_auth
def index():
    """
    Old function to be changed for full configuration search
    """
    navigation = True
    if request.method == "POST":
        if request.form.get("search_input"):
            ipaddress = request.form.get("search_input")
            device_id = get_device_id(ipaddress=ipaddress)["id"]
            app.logger.info(f'User {session["user"]} search device {ipaddress}')
            check_last_config = get_last_config_for_device(device_id=device_id)
            if check_last_config is not None:
                check_previous_config = check_if_previous_configuration_exists(
                    device_id=device_id
                )
                if check_previous_config is True:
                    return redirect(f"/diff_page/{ipaddress}")

                elif check_previous_config is False:
                    flash("This device has no previous configuration ", "info")
                    return redirect(f"/config_page/{ipaddress}")
            else:
                flash("Device not found, check the entered ipaddress", "warning")
                return render_template(
                    "index.html", ipaddress=ipaddress, navigation=navigation
                )
    else:
        return render_template("index.html", navigation=navigation)


# Config compare page
@app.route("/diff_page/<device_id>", methods=["POST", "GET"])
@check_auth
def diff_page(device_id):
    """
    This function render configs compare page
    """
    navigation = True
    logger.info(f"User: {session['user']} opens the config compare page")
    check_previous_config = check_if_previous_configuration_exists(device_id=device_id)
    config_timestamp = get_all_cfg_timestamp_for_device(device_id=device_id)
    last_config_dict = get_last_config_for_device(device_id=device_id)
    device_environment = get_last_env_for_device(device_id=device_id)
    if check_previous_config is True:
        if last_config_dict is not None:
            last_config = last_config_dict["last_config"]
            timestamp = last_config_dict["timestamp"]
            return render_template(
                "diff_page.html",
                last_config=last_config,
                navigation=navigation,
                config_timestamp=config_timestamp,
                timestamp=timestamp,
                device_environment=device_environment,
            )
        else:
            flash("Device not found?", "info")
            return redirect(url_for("index"))
    elif check_previous_config is False and last_config_dict is not None:
        flash("This device has no previous configuration ", "info")
        return redirect(f"/config_page/{device_id}")
    else:
        flash("Device not found?", "info")
        return redirect(url_for("index"))


# Get devices status page
@app.route("/", methods=["POST", "GET"])
@check_auth
def devices():
    """
    This function render devices page
    """
    navigation = True
    logger.info(f"User: {session['user']} opens the devices page")
    if request.method == "POST":
        if request.form.get("add_device_btn"):
            add_hostname = request.form.get("add_hostname")
            add_ipaddress = request.form.get("add_ipaddress")
            add_platform = request.form.get("add_platform")
            if add_hostname == "" or add_ipaddress == "" or add_platform == "":
                flash("All fields must be filled", "warning")
            else:
                if check_ip(add_ipaddress):
                    result = add_device(
                        hostname=add_hostname,
                        ipaddress=add_ipaddress,
                        connection_driver=add_platform,
                    )
                    if result:
                        flash("The device has been added", "success")
                    else:
                        flash("An error occurred while adding the device", "danger")
                else:
                    flash("The IP address is incorrect", "warning")
        if request.form.get("del_device_btn"):
            device_id = int(request.form.get("del_device_btn"))
            result = delete_device(device_id=device_id)
            if result:
                flash("The device has been removed", "success")
            else:
                flash("An error occurred while deleting the device", "danger")
        if request.form.get("edit_device_btn"):
            device_id = int(request.form.get(f"edit_device_btn"))
            edit_hostname = request.form.get(f"hostname_{device_id}")
            edit_ipaddress = request.form.get(f"ipaddress_{device_id}")
            edit_platform = request.form.get(f"platform_{device_id}")
            if edit_hostname == "" or edit_ipaddress == "" or edit_platform == "":
                flash("All fields must be filled", "warning")
            else:
                if check_ip(edit_ipaddress):
                    result = update_device(
                        hostname=edit_hostname,
                        device_id=device_id,
                        new_ipaddress=edit_ipaddress,
                        connection_driver=edit_platform,
                    )
                    if result:
                        flash("The device has been updated", "success")
                    else:
                        flash("An error occurred while updating the device", "danger")
                else:
                    flash("The new IP address is incorrect", "warning")
        return render_template(
            "devices.html", navigation=navigation, devices_env=get_devices_env()
        )
    else:
        return render_template(
            "devices.html", navigation=navigation, devices_env=get_devices_env()
        )


# Authorization form
@app.route("/login", methods=["POST", "GET"])
def login():
    """
    This function render authorization page
    """
    navigation = False
    if "user" not in session or session["user"] == "":
        if request.method == "POST":
            page_email = request.form["email"]
            page_password = request.form["password"]
            # Authorization method check
            if local_login:

                auth_user = AuthUsers

                check = auth_user(email=page_email, password=page_password).check_user()
                if check:
                    session["user"] = page_email
                    session["rights"] = "admin"
                    print(session)
                    flash("You were successfully logged in", "success")
                    return redirect(url_for("devices"))
                else:
                    flash("May be email or password is incorrect?", "danger")
                    return render_template("login.html", navigation=navigation)
            else:
                ldap_connect = LdapFlask(page_email, page_password)

                if ldap_connect.bind():
                    session["user"] = page_email
                    session["user"] = page_email
                    session["rights"] = "admin"
                    print(session)
                    flash("You were successfully logged in", "success")
                    return redirect(url_for("devices"))
                else:
                    flash("May be the password is incorrect?", "danger")
                    return render_template("login.html", navigation=navigation)
        else:
            return render_template("login.html", navigation=navigation)

    else:
        session["user"] = ""
        flash("You were successfully logged out", "warning")
        return redirect(url_for("login"))


# Ajax function get previous configs for device
@app.route("/previous_config/", methods=["POST", "GET"])
@check_auth
def previous_config():
    """
    Ajax function get previous configs for device
    """
    if request.method == "POST":
        previous_config_data = request.get_json()
        device_id = previous_config_data["device_id"]
        previous_timestamp = previous_config_data["date"]
        previous_config_dict = get_previous_config(
            device_id=device_id, db_timestamp=previous_timestamp
        )
        result = "ok"
        if previous_config is not None:
            return jsonify(
                {
                    "status": result,
                    "config_id": previous_config_dict["id"],
                    "previous_config_file": previous_config_dict["device_config"],
                    "previous_config_file_split": previous_config_dict[
                        "device_config"
                    ].splitlines(),
                    "timestamp": previous_config_dict["timestamp"],
                }
            )
        else:
            result = "none"
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": None,
                }
            )


@app.route("/config_page/<device_id>", methods=["POST", "GET"])
@check_auth
def config_page(device_id):
    """
    This function renders config page
    """
    navigation = True
    logger.info(f"User: {session['user']} opens the config compare page")
    if request.method == "POST":
        if request.form.get("del_config_btn"):
            config_id = request.form.get("del_config_btn")
            result = delete_config(config_id=config_id)
            if result:
                flash("Config has been deleted", "success")
            else:
                flash("Delete config error", "warning")
        #
        previous_configs_timestamp = get_all_cfg_timestamp_for_device(
            device_id=device_id
        )
        config_timestamp_list = get_all_cfg_timestamp_for_config_page(
            device_id=device_id
        )
        last_config_dict = get_last_config_for_device(device_id=device_id)
        check_previous_config = check_if_previous_configuration_exists(
            device_id=device_id
        )
        device_environment = get_last_env_for_device(device_id=device_id)
        if last_config_dict is not None:
            return render_template(
                "config_page.html",
                navigation=navigation,
                config_id=last_config_dict["id"],
                last_config=last_config_dict["last_config"],
                timestamp=last_config_dict["timestamp"],
                config_timestamp_list=config_timestamp_list,
                check_previous_config=check_previous_config,
                previous_configs_timestamp=previous_configs_timestamp,
                device_environment=device_environment,
            )
        else:
            flash("Device not found?", "info")
            return redirect(url_for("index"))
    else:
        previous_configs_timestamp = get_all_cfg_timestamp_for_device(
            device_id=device_id
        )
        config_timestamp_list = get_all_cfg_timestamp_for_config_page(
            device_id=device_id
        )
        last_config_dict = get_last_config_for_device(device_id=device_id)
        check_previous_config = check_if_previous_configuration_exists(
            device_id=device_id
        )
        device_environment = get_last_env_for_device(device_id=device_id)
        if last_config_dict is not None:
            return render_template(
                "config_page.html",
                navigation=navigation,
                config_id=last_config_dict["id"],
                ipaddress=device_environment["device_ip"],
                last_config=last_config_dict["last_config"],
                timestamp=last_config_dict["timestamp"],
                config_timestamp_list=config_timestamp_list,
                check_previous_config=check_previous_config,
                previous_configs_timestamp=previous_configs_timestamp,
                device_environment=device_environment,
            )
        else:
            flash("Device not found?", "info")
            return redirect(url_for("index"))


# Ajax function to check device status
@app.route("/device_status/", methods=["POST", "GET"])
@check_auth
def device_status():
    """
    Ajax function to check device status
    """
    if request.method == "POST":
        previous_config_data = request.get_json()
        ipaddress = previous_config_data["device"]
        driver = previous_config_data["driver"]

        result = backup_config_on_db(ipaddress=ipaddress, napalm_driver=driver)
        print(result)
        return jsonify(
            {
                "status": True,
                "device_id": result["device_id"],
                "device_ip": result["device_ip"],
                "hostname": result["hostname"],
                "timestamp": result["timestamp"],
                "last_changed": str(result["last_changed"]),
                "connection_status": str(result["connection_status"]),
            }
        )


# TO DO
# Ajax function get devices status
@app.route("/restore_config/", methods=["POST", "GET"])
@check_auth
def restore_config():
    if request.method == "POST":
        pass


# NABS settings route
@app.route("/settings/", methods=["POST", "GET"])
@check_auth
def settings_page():
    """
    This function render settings page
    """
    navigation = True
    auth_users = AuthUsers
    if request.method == "POST":
        if request.form.get("edit_user_btn"):
            user_id = request.form.get(f"edit_user_btn")
            username = request.form.get(f"username_{user_id}")
            email = request.form.get(f"email_{user_id}")
            role = request.form.get(f"role_{user_id}")
            password = request.form.get(f"password_{user_id}")

            result = auth_users(
                user_id=user_id,
                username=username,
                email=email,
                role=role,
                password=password,
            ).update_user()

            if result:
                flash(f"User {username} has been updated", "success")

            else:
                flash("Update Error", "warning")
        #
        if request.form.get("del_user_btn"):
            user_id = request.form.get(f"del_user_btn")

            result = auth_users(user_id=user_id).del_user()

            if result:
                flash(f"User has been deleted", "success")

            else:
                flash("delete Error", "warning")
        #
        if request.form.get("add_user_btn"):
            username = request.form.get(f"username")
            email = request.form.get(f"email")
            role = request.form.get(f"role")
            password = request.form.get(f"password")

            result = auth_users(
                username=username, email=email, role=role, password=password
            ).add_user()
            if result:
                flash(f"User has been added", "success")

            else:
                flash("Added Error", "warning")
        return render_template(
            "settings.html",
            users_list=auth_users.get_users_list(),
            navigation=navigation,
        )
    else:
        return render_template(
            "settings.html",
            users_list=auth_users.get_users_list(),
            navigation=navigation,
        )
