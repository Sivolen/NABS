import collections
from multiprocessing import Pool

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
from app.modules.backuper import run_backup_config_on_db
from app.modules.crypto import decrypt
from app.modules.dbutils.db_utils import (
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
    get_devices_by_rights,
    get_device_setting,
)

from app.modules.dbutils.db_groups import (
    get_all_devices_group,
    add_device_group,
    del_device_group,
    get_user_group,
    add_user_group,
    delete_user_group,
    get_all_user_group,
    get_user_group_name,
)

from app.modules.dbutils.db_user_roles import (
    create_user_role,
    delete_user_role,
    get_user_roles,
)

from app.modules.dbutils.db_users_permission import (
    get_associate_user_group,
    get_devices_list,
    create_associate_user_group,
    delete_associate_by_id,
    update_associate_device_group,
    get_users_group,
    get_associate_device_group,
    create_associate_device_group,
    delete_associate_user_group,
    convert_user_group_in_association_id,
    get_association_user_and_device,
    delete_associate_by_list,
)

from app.utils import check_ip

from app.modules.dbutils.db_user_rights import (
    check_user_rights,
    check_user_role_redirect,
    check_user_role_block,
    check_user_permission,
)

from app import logger

from app.modules.auth.auth_users_local import AuthUsers

from app.modules.auth.auth_users_ldap import LdapFlask, check_auth

from config import auth_methods, TOKEN, drivers, proccesor_pool


@app.errorhandler(404)
@check_auth
def page_not_found(error):
    # note that we set the 404 status explicitly
    logger.info(f"User: {session['user']}, role {session['rights']} opens page {error}")
    return render_template("404.html"), 404


# Home page and search devices
@app.route("/search", methods=["POST", "GET"])
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


# Config compare page
@app.route("/diff_page/<device_id>", methods=["POST", "GET"])
@check_auth
@check_user_permission
def diff_page(device_id):
    """
    This function render configs compare page
    """
    navigation: bool = True
    logger.info(
        f"User: {session['user']} {session['rights']} opens the config compare page"
    )
    check_previous_config: bool = check_if_previous_configuration_exists(
        device_id=device_id
    )
    config_timestamp: list = get_all_cfg_timestamp_for_device(device_id=device_id)
    last_config_dict: dict = get_last_config_for_device(device_id=device_id)
    device_environment: dict = get_last_env_for_device(device_id=device_id)

    if request.method == "POST" and request.form.get("del_config_btn"):
        config_id: str = request.form.get("del_config_btn")
        result: bool = delete_config(config_id=config_id)
        if result:
            logger.info(
                f"User: {session['user']} {session['rights']} removed the {config_id} configuration on the comparison page"
            )
            flash("Config has been deleted", "success")
        else:
            logger.info(
                f"User: {session['user']} {session['rights']} tried to delete the {config_id} configuration on the comparison page"
            )
            flash("Delete config error", "warning")

    if check_previous_config and last_config_dict is not None:
        return render_template(
            "diff_page.html",
            last_config=last_config_dict["last_config"],
            last_confog_id=last_config_dict["id"],
            navigation=navigation,
            config_timestamp=config_timestamp,
            timestamp=last_config_dict["timestamp"],
            device_environment=device_environment,
        )

    if not check_previous_config and last_config_dict is not None:
        flash("This device has no previous configuration ", "info")
        return redirect(f"/config_page/{device_id}")

    if not check_previous_config and last_config_dict is None:
        flash("Device not found?", "info")
        return redirect(url_for("devices"))


# Get devices status page
@app.route("/", methods=["POST", "GET"])
@check_auth
def devices():
    """
    This function render devices page
    """
    navigation: bool = True
    group_result: bool = True
    logger.info(f"User: {session['user']} opens the devices page")

    # If there are post requests from the form, we start processing these requests [add, delete, change device].
    if request.method == "POST" and request.form.get("add_device_btn"):
        user_groups: list = request.form.getlist("add_user_groups")
        page_data = {
            "group_id": int(request.form.get("device_group")),
            "hostname": request.form.get("add_hostname"),
            "ipaddress": request.form.get("add_ipaddress"),
            "connection_driver": request.form.get("add_platform"),
            "ssh_user": request.form.get("add_username"),
            "ssh_pass": request.form.get("add_password"),
            "ssh_port": int(request.form.get("add_port")),
        }
        logger.info(
            f"User: {session['user']} add a new device {page_data['ipaddress']}"
        )
        if (
            not page_data["hostname"]
            or not page_data["ipaddress"]
            or not page_data["connection_driver"]
            or not page_data["ssh_user"]
            or not page_data["ssh_pass"]
            or not page_data["ssh_port"]
        ):
            flash("All fields must be filled", "warning")
            return redirect(url_for("devices"))

        if get_device_id(ipaddress=page_data["ipaddress"]):
            logger.info(
                f"User: {session['user']} tried to add a device: {page_data['ipaddress']} that is already in the database"
            )
            flash("The device is already in the database", "warning")
            return redirect(url_for("devices"))

        if not check_ip(page_data["ipaddress"]):
            logger.info(
                f"User: {session['user']} tried to add a device with the wrong ip address {page_data['ipaddress']}"
            )
            flash("The IP address is incorrect", "warning")
            return redirect(url_for("devices"))

        result = add_device(**page_data)
        if not result:
            logger.info(
                f"Adding a new device {page_data['ipaddress']} by user {session['user']} ended with an error"
            )
            flash(
                f"There was an error when chiseling a new device {page_data['ipaddress']}",
                "danger",
            )
            return redirect(url_for("devices"))

        if result and user_groups != []:
            device_id = get_device_id(ipaddress=page_data["ipaddress"])["id"]
            for group_id in user_groups:
                group_result = create_associate_device_group(
                    device_id=int(device_id),
                    user_group_id=int(group_id),
                )
                if not group_result:
                    flash(
                        "An error occurred while adding the user group",
                        "danger",
                    )
            return redirect(url_for("devices"))
        if result:
            logger.info(
                f"User: {session['user']} added a new device {page_data['ipaddress']}"
            )
            flash("The device has been added", "success")
            return redirect(url_for("devices"))

    # Delete a new device
    if request.method == "POST" and request.form.get("del_device_btn"):
        device_id: int = int(request.form.get("del_device_btn"))
        logger.info(
            f"User: {session['user']} is trying to remove the device 10 {device_id}"
        )
        result: bool = delete_device(device_id=device_id)

        if not result:
            logger.info(f"Device {device_id} removed")
            flash(f"An error occurred when deleting a device {device_id}", "danger")
            return redirect(url_for("devices"))

        logger.info(f"Device {device_id} removed")
        flash("The device has been removed", "success")
        return redirect(url_for("devices"))

    # Change the device
    if request.method == "POST" and request.form.get("edit_device_btn"):
        edit_user_group = request.form.getlist(f"user-group")
        edit_user_group = list(map(int, edit_user_group))
        page_data = {
            "group_id": int(request.form.get(f"device-group")),
            "hostname": request.form.get(f"hostname"),
            "device_id": int(request.form.get(f"edit_device_btn")),
            "new_ipaddress": request.form.get(f"ipaddress"),
            "connection_driver": request.form.get(f"platform"),
            "ssh_user": request.form.get(f"username"),
            "ssh_pass": request.form.get(f"password"),
            "ssh_port": int(request.form.get(f"port")),
        }
        logger.info(
            f"User: {session['user']} tries to edit the device {page_data['new_ipaddress']}"
        )
        if (
            not page_data["hostname"]
            or not page_data["new_ipaddress"]
            or not page_data["connection_driver"]
            or not page_data["ssh_user"]
            or not page_data["ssh_pass"]
            or not page_data["ssh_port"]
        ):
            flash("All fields must be filled", "warning")
            return redirect(url_for("devices"))

        if not check_ip(page_data["new_ipaddress"]):
            logger.info(f"The new IP address is incorrect {page_data['new_ipaddress']}")
            flash("The new IP address is incorrect", "warning")
            return redirect(url_for("devices"))

        # Update device data
        result = update_device(**page_data)

        if not result:
            logger.info(f"The new IP address is incorrect {page_data['new_ipaddress']}")
            flash("The new IP address is incorrect", "warning")
            return redirect(url_for("devices"))

        if result and edit_user_group != []:
            old_user_groups: list = get_association_user_and_device(
                user_id=session["user_id"],
                device_id=page_data["device_id"],
            )
            converted_groups_list: list = convert_user_group_in_association_id(
                user_id=session["user_id"],
                device_id=page_data["device_id"],
                user_groups_list=edit_user_group,
            )
            if not collections.Counter(old_user_groups) == collections.Counter(
                converted_groups_list
            ) or not len(edit_user_group) == len(old_user_groups):
                delete_associate_by_list(associate_id=old_user_groups)
                for group in edit_user_group:
                    group_result = create_associate_device_group(
                        device_id=int(page_data["device_id"]),
                        user_group_id=int(group),
                    )
                if not group_result:
                    flash(
                        f"The {page_data['new_ipaddress']} device was updated, but an error occurred when updating user groups",
                        "warning",
                    )

                    logger.debug(
                        f"The {page_data['new_ipaddress']} device was updated, but an error occurred when updating user groups"
                    )
                    return redirect(url_for("devices"))

            flash("The device has been updated", "success")
            logger.info(f"The device {page_data['new_ipaddress']} has been updated ")
            return redirect(url_for("devices"))
        #
        if result and edit_user_group == []:
            old_user_groups: list = get_association_user_and_device(
                user_id=session["user_id"],
                device_id=page_data["device_id"],
            )
            if not old_user_groups:
                logger.info(
                    f"The device {page_data['new_ipaddress']} has been updated "
                )
                flash("The device has been updated", "success")
                return redirect(url_for("devices"))

            group_result: bool = delete_associate_by_list(associate_id=old_user_groups)
            if not group_result:
                logger.info(
                    f"The device {page_data['new_ipaddress']} has been updated but an error occurred while deleting user groups"
                )
                flash(
                    f"The device {page_data['new_ipaddress']} has been updated but an error occurred while deleting user groups",
                    "warning",
                )

            logger.info(f"The device {page_data['new_ipaddress']} has been updated ")
            flash("The device has been updated", "success")
            return redirect(url_for("devices"))

    # Render template if get request
    if session["rights"] == "sadmin":
        devices_table = get_devices_env()
        user_groups = get_associate_user_group(user_id=session["user_id"])
    else:
        devices_table = get_devices_by_rights(user_id=session["user_id"])
        user_groups = get_associate_user_group(user_id=session["user_id"])
    # Loading the page if a GET request arrives
    return render_template(
        "devices.html",
        navigation=navigation,
        devices_env=devices_table,
        groups=get_all_devices_group(),
        user_groups=user_groups,
        drivers=drivers,
    )


# Authorization form
@app.route("/login", methods=["POST", "GET"])
def login():
    """
    This function render authorization page
    """
    navigation = False
    # if "user" in session or session["user"] != "":
    if "user" not in session or session["user"] == "":
        if request.method == "POST":
            auth_user = AuthUsers
            page_email = request.form["email"]
            page_password = request.form["password"]
            # Authorization method check
            user_id = auth_user(email=page_email).get_user_id_by_email()
            if user_id is None:
                flash(f"User not found", "warning")
                return redirect(url_for("login"))
            auth_method = auth_user(email=page_email).get_user_auth_method()
            if user_id is not None and auth_method == "local":
                check = auth_user(email=page_email, password=page_password).check_user()
                if not check:
                    flash("May be email or password is incorrect?", "danger")
                    return render_template("login.html", navigation=navigation)
                session["user"] = page_email
                session["rights"] = check_user_rights(user_email=page_email)
                session["user_id"] = user_id
                session["allowed_devices"] = get_users_group(user_id=user_id)
                flash("You were successfully logged in", "success")
                return redirect(url_for("devices"))

            if user_id is not None and auth_method == "ldap":
                ldap_connect = LdapFlask(page_email, page_password)
                if not ldap_connect.bind():
                    flash("May be the password is incorrect?", "danger")
                    return render_template("login.html", navigation=navigation)
                session["user"] = page_email
                session["rights"] = check_user_rights(user_email=page_email)
                session["user_id"] = user_id
                session["allowed_devices"] = get_users_group(user_id=user_id)
                flash("You were successfully logged in", "success")
                return redirect(url_for("devices"))

    else:
        session["user"] = ""
        flash("You were successfully logged out", "warning")
        return redirect(url_for("login"))

    return render_template("login.html", navigation=navigation)


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
        if previous_config is None:
            result = "none"
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": None,
                }
            )

        result = "ok"
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


@app.route("/config_page/<device_id>", methods=["POST", "GET"])
@check_auth
@check_user_permission
def config_page(device_id):
    """
    This function renders config page
    """
    navigation = True
    logger.info(f"User: {session['user']} opens the config compare page")
    if request.method == "POST" and request.form.get("del_config_btn"):
        config_id = request.form.get("del_config_btn")
        result = delete_config(config_id=config_id)
        if result:
            flash("Config has been deleted", "success")
        else:
            flash("Delete config error", "warning")
        #
    previous_configs_timestamp = get_all_cfg_timestamp_for_device(device_id=device_id)
    config_timestamp_list = get_all_cfg_timestamp_for_config_page(device_id=device_id)
    last_config_dict = get_last_config_for_device(device_id=device_id)
    check_previous_config = check_if_previous_configuration_exists(device_id=device_id)
    device_environment = get_last_env_for_device(device_id=device_id)
    if last_config_dict is None:
        flash("Device not found?", "info")
        return redirect(url_for("devices"))

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


# Ajax function to check device status
@app.route("/device_status/", methods=["POST", "GET"])
@check_auth
def device_status():
    """
    Ajax function to check device status
    """
    if request.method == "POST":
        previous_config_data = request.get_json()

        with Pool(processes=proccesor_pool) as pool:
            result = pool.apply_async(
                run_backup_config_on_db, args=(previous_config_data,)
            )
            result_dict = result.get()

        return jsonify(
            {
                "status": True,
                "device_id": result_dict["device_id"],
                "device_ip": result_dict["device_ip"],
                "hostname": result_dict["hostname"],
                "vendor": result_dict["vendor"],
                "timestamp": result_dict["timestamp"],
                "last_changed": str(result_dict["last_changed"]),
                "connection_status": str(result_dict["connection_status"]),
            }
        )


# TO DO
# Ajax function get devices status
@app.route("/restore_config/", methods=["POST", "GET"])
@check_auth
@check_user_role_block
def restore_config():
    if request.method == "POST":
        pass


# NABS settings route
@app.route("/settings/", methods=["POST", "GET"])
@check_auth
@check_user_role_redirect
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
            auth_method = request.form.get(f"auth_method_{user_id}")
            result = auth_users(
                user_id=user_id,
                username=username,
                email=email,
                role=role,
                password=password,
                auth_method=auth_method,
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
            auth_method = request.form.get(f"auth_method")
            result = auth_users(
                username=username,
                email=email,
                role=role,
                password=password,
                auth_method=auth_method,
            ).add_user()
            if result:
                flash(f"User has been added", "success")

            else:
                flash("Added Error", "warning")

        if request.form.get("add_group_btn"):
            group_name = request.form.get(f"group")
            result = add_device_group(
                group_name=group_name,
            )
            if result:
                flash(f"Group has been added", "success")

            else:
                flash("Added group Error", "warning")
        #
        if request.form.get("del_group_btn"):
            group_id = int(request.form.get(f"del_group_btn"))
            print(11, group_id)
            result = del_device_group(
                group_id=group_id,
            )
            if result:
                flash(f"Group has been deleted", "success")

            else:
                flash("Deleting group Error", "warning")
        #
        if request.form.get("add_role_btn"):
            role_name = request.form.get(f"role")
            result = create_user_role(
                role_name=role_name,
            )
            if result:
                flash(f"Role has been added", "success")

            else:
                flash("Added role Error", "warning")
        #
        if request.form.get("del_role_btn"):
            role_id = int(request.form.get(f"del_role_btn"))
            result = delete_user_role(
                role_id=role_id,
            )
            if result:
                flash(f"Role has been deleted", "success")

            else:
                flash("Deleting role Error", "warning")
        #
        if request.form.get("add_user_group_btn"):
            user_group_name = request.form.get(f"user_group")
            result = add_user_group(
                user_group_name=user_group_name,
            )
            if result:
                flash(f"Group has been added", "success")

            else:
                flash("Added group Error", "warning")
        #
        if request.form.get("del_user_group_btn"):
            user_group_id = int(request.form.get(f"del_user_group_btn"))
            result = delete_user_group(
                user_group_id=user_group_id,
            )
            if result:
                flash(f"Group has been deleted", "success")
            else:
                flash("Deleting group Error", "warning")
        #
    return render_template(
        "settings.html",
        users_list=auth_users.get_users_list(),
        groups=get_all_devices_group(),
        navigation=navigation,
        user_roles=get_user_roles(),
        user_groups=get_user_group(),
        auth_methods=auth_methods,
    )


@app.route("/associate_settings/<user_group_id>", methods=["POST", "GET"])
@check_auth
@check_user_role_redirect
def associate_settings(user_group_id: int):
    navigation = True
    logger.info(
        f"User: {session['user']} ({session['rights']}) opens the user settings"
    )
    if request.method == "POST":
        if request.form.get("add_associate"):
            device_id = request.form.get(f"devices")

            result = create_associate_device_group(
                device_id=int(device_id),
                user_group_id=int(user_group_id),
            )
            if result:
                flash(f"Add association success", "success")

            else:
                flash("Update Error", "warning")
        #
        if request.form.get("del_associate_btn"):
            associate_id = request.form.get(f"del_associate_btn")
            result = delete_associate_by_id(
                associate_id=associate_id,
            )
            if result:
                flash(f"Delete association success", "success")

            else:
                flash("Delete Error", "warning")
        #
        if request.form.get("edit_associate_btn"):
            associate_id = request.form.get(f"edit_associate_btn")
            group_id = request.form.get(f"groups")
            device_id = request.form.get(f"devices")
            result = update_associate_device_group(
                associate_id=int(associate_id),
                user_group_id=int(group_id),
                device_id=int(device_id),
            )
            if result:
                flash(f"Delete association success", "success")

            else:
                flash("Delete Error", "warning")
        #
    return render_template(
        "associate_settings.html",
        navigation=navigation,
        associate_user_group=get_associate_device_group(
            user_group_id=int(user_group_id)
        ),
        devices=get_devices_list(),
        groups=get_all_user_group(),
        user_group_name=get_user_group_name(user_group_id=user_group_id),
    )


@app.route("/user_group/<user_id>", methods=["POST", "GET"])
@check_auth
@check_user_role_redirect
def user_group(user_id: int):
    navigation = True
    logger.info(
        f"User: {session['user']} ({session['rights']}) opens the user user group"
    )
    auth_user = AuthUsers
    if request.method == "POST":
        if request.form.get("add_associate_user_group_btn"):
            user_group_id = request.form.get(f"user_group_name")

            result = create_associate_user_group(
                user_group_id=int(user_group_id),
                user_id=int(user_id),
            )
            if result:
                flash(f"Add association success", "success")
            else:
                flash("Update Error", "warning")
            #
        if request.form.get("del_group_associate_btn"):
            user_group_id = request.form.get(f"del_group_associate_btn")

            result = delete_associate_user_group(
                associate_id=int(user_group_id),
            )

            if result:
                flash(f"Delete association success", "success")
            else:
                flash("Delete Error", "warning")
    #
    return render_template(
        "user_group.html",
        navigation=navigation,
        associate_user_group=get_associate_user_group(user_id=int(user_id)),
        user_group=get_all_user_group(),
        user_email=auth_user(user_id=user_id).get_user_email_by_id(),
    )


@app.route("/device_settings/", methods=["POST", "GET"])
@check_auth
@check_user_role_block
def device_settings():
    """
    Ajax function to check device status
    """
    if request.method == "POST":
        data = request.get_json()
        device_id = data["device_id"]
        user_groups = get_associate_user_group(user_id=session["user_id"])
        device_setting = get_device_setting(device_id=device_id)
        print(device_setting)
        if device_setting["ssh_pass"] is not None:
            ssh_pass = decrypt(ssh_pass=device_setting["ssh_pass"], key=TOKEN)
        else:
            ssh_pass = "The password is not set"
        return jsonify(
            {
                "device_group": device_setting["device_group"],
                "device_hostname": device_setting["device_hostname"],
                "device_ipaddress": device_setting["device_ip"],
                "device_driver": device_setting["connection_driver"],
                "ssh_user": device_setting["ssh_user"],
                "ssh_pass": ssh_pass,
                "ssh_port": device_setting["ssh_port"],
                "user_group": device_setting["user_group"],
                "drivers": drivers,
                "devices_group": get_all_devices_group(),
                "user_groups": user_groups,
            }
        )
