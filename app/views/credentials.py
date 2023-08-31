from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)
from app.modules.crypto import encrypt
from app.modules.dbutils.db_credentials import (
    add_credentials,
    del_credentials,
    update_credentials,
    get_allowed_credentials,
)
from app.modules.dbutils.db_devices import (
    get_allowed_devices_by_right,
    update_device_credentials,
)
from app.modules.dbutils.db_users_permission import get_associate_user_group
from app.modules.dbutils.db_user_rights import check_user_role_block
from app.modules.auth.auth_users_ldap import check_auth
from config import TOKEN


@check_auth
@check_user_role_block
def credentials():
    """
    This function render credentials page
    """
    credentials_menu_active: bool = True
    settings_menu_active: bool = True

    if request.method == "POST" and request.form.get("add_profile_btn"):
        credentials_name = request.form.get(f"credentials_name")
        credentials_username = request.form.get(f"credentials_username")
        credentials_password = request.form.get(f"credentials_password")
        credentials_user_group = request.form.get(f"add_user_groups")

        result: bool = add_credentials(
            credentials_name=credentials_name,
            credentials_username=credentials_username,
            credentials_password=encrypt(ssh_pass=credentials_password, key=TOKEN),
            credentials_user_group=int(credentials_user_group),
        )
        if not result:
            flash("Added credentials profile Error", "warning")
            return redirect(url_for("credentials"))

        flash(f"Credentials profile has been added", "success")
        return redirect(url_for("credentials"))
    #
    if request.method == "POST" and request.form.get("del_profile_btn"):
        credentials_id = int(request.form.get(f"del_profile_btn"))
        result: bool = del_credentials(
            credentials_id=credentials_id,
        )
        if not result:
            flash("Deleting credentials profile Error", "warning")
            return redirect(url_for("credentials"))

        flash(f"Credentials profile has been deleted", "success")
        return redirect(url_for("credentials"))
    #
    if request.method == "POST" and request.form.get("edit_dbprofile_btn"):
        page_data = {
            "credentials_id": int(request.form.get(f"edit_dbprofile_btn")),
            "credentials_name": request.form.get(f"db_credentials_name"),
            "credentials_username": request.form.get(f"db_credentials_username"),
            "credentials_password": request.form.get(f"db_credentials_password"),
            "credentials_user_group": request.form.get(f"db_user-group"),
        }
        result: bool = update_credentials(
            credentials_id=page_data["credentials_id"],
            credentials_name=page_data["credentials_name"],
            credentials_username=page_data["credentials_username"],
            credentials_password=page_data["credentials_password"],
            credentials_user_group=int(page_data["credentials_user_group"]),
        )
        if not result:
            flash("Modify credentials profile Error", "warning")
            return redirect(url_for("credentials"))

        flash(f"Credentials profile has been modified", "success")
        return redirect(url_for("credentials"))

    if request.method == "POST" and request.form.get("add_cred_associate"):
        credentials_id: int = int(request.form.get("add_cred_associate"))
        devices_list: list = request.form.getlist("devices_list")
        if not devices_list:
            flash("Device not selected", "info")
            return redirect(url_for("associate_settings"))
        for device_id in devices_list:
            result: bool = update_device_credentials(
                device_id=int(device_id),
                credentials_id=credentials_id,
            )
            if not result:
                flash("Update associate Error", "warning")
                return redirect(url_for("credentials"))

        flash(f"Add association success", "success")
        return redirect(url_for("credentials"))

    associate_user_group = get_associate_user_group(user_id=session["user_id"])
    # If get request
    return render_template(
        "credentials.html",
        credentials_menu_active=credentials_menu_active,
        settings_menu_active=settings_menu_active,
        add_user_groups=associate_user_group,
        devices=get_allowed_devices_by_right(session["user_id"]),
        allowed_credentials=get_allowed_credentials(user_id=session["user_id"]),
    )