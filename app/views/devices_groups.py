from flask import (
    render_template,
    request,
    flash,
    url_for,
    redirect,
)
from app.modules.dbutils.db_groups import (
    get_all_devices_group,
    add_device_group,
    del_device_group,
)
from app.modules.dbutils.db_user_rights import check_user_role_redirect
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_role_redirect
def devices_groups():
    settings_menu_active: bool = True
    devices_groups_active: bool = True
    if request.method == "POST" and request.form.get("add_group_btn"):
        group_name = request.form.get(f"group")
        result: bool = add_device_group(
            group_name=group_name,
        )
        if not result:
            flash("Added group Error", "warning")
            return redirect(url_for("devices_groups"))

        flash(f"Group has been added", "success")
        return redirect(url_for("devices_groups"))
    #
    if request.method == "POST" and request.form.get("del_group_btn"):
        group_id = int(request.form.get(f"del_group_btn"))
        result: bool = del_device_group(
            group_id=group_id,
        )
        if not result:
            flash("Deleting group Error", "warning")
            return redirect(url_for("devices_groups"))

        flash(f"Group has been deleted", "success")
        return redirect(url_for("devices_groups"))
    #
    return render_template(
        "devices_groups.html",
        devices_groups_active=devices_groups_active,
        settings_menu_active=settings_menu_active,
        groups=get_all_devices_group(),
    )
