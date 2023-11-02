from flask import render_template, request, flash, redirect, url_for, jsonify

from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_drivers import (
    add_driver,
    get_all_drivers,
    delete_custom_driver,
    get_driver_settings,
    update_driver,
)


@check_auth
def drivers():
    """
    Function for custom drivers page
    """
    drivers_menu_active: bool = True
    settings_menu_active: bool = True
    #
    if request.method == "POST" and request.form.get("add_driver"):
        page_data: dict = {
            "drivers_name": request.form.get("name"),
            "drivers_vendor": request.form.get("vendor"),
            "drivers_model": request.form.get("model"),
            "drivers_commands": request.form.get("commands"),
        }
        result: bool = add_driver(**page_data)
        if not result:
            flash("Addition drivers profile Error", "warning")
            return redirect(url_for("drivers"))

        flash(f"Drivers profile has been added", "success")
        return redirect(url_for("drivers"))
    #
    if request.method == "POST" and request.form.get("edit_driver_btn"):
        page_data: dict = {
            "custom_drivers_id": int(request.form.get("edit_driver_btn")),
            "drivers_name": request.form.get("edit-name"),
            "drivers_vendor": request.form.get("edit-vendor"),
            "drivers_model": request.form.get("edit-model"),
            "drivers_commands": request.form.get("edit-commands"),
        }
        result = update_driver(**page_data)
        if not result:
            flash("Driver profile update error", "warning")
            return redirect(url_for("drivers"))

        flash(f"Driver profile update completed successfully", "success")
        return redirect(url_for("drivers"))
    #
    if request.method == "POST" and request.form.get("del_driver_btn"):
        custom_driver_id: int = int(request.form.get("del_driver_btn"))
        result: bool = delete_custom_driver(custom_driver_id=custom_driver_id)
        if not result:
            flash("Deleting command Error", "warning")
            return redirect(url_for("drivers"))

        flash(f"Deleting command successful", "success")
        return redirect(url_for("drivers"))
    #
    return render_template(
        "drivers.html",
        drivers=get_all_drivers(),
        drivers_menu_active=drivers_menu_active,
        settings_menu_active=settings_menu_active,
    )


#  Ajax functions for getting the driver settings
def drivers_settings():
    """
    Ajax functions for getting the driver settings
    """
    if request.method == "POST":
        data = request.get_json()
        custom_drivers_id = int(data["custom_drivers_id"])
        driver_settings = get_driver_settings(custom_drivers_id=custom_drivers_id)
        if not driver_settings:
            return jsonify({"status": "none"})
        return jsonify(
            {
                "status": "success",
                "custom_drivers_id": driver_settings["custom_drivers_id"],
                "drivers_name": driver_settings["drivers_name"],
                "drivers_vendor": driver_settings["drivers_vendor"],
                "drivers_model": driver_settings["drivers_model"],
                "drivers_commands": driver_settings["drivers_commands"],
            }
        )
