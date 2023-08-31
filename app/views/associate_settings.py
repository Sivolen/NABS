from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)
from app.modules.dbutils.db_groups import (
    get_all_user_group,
    get_user_group_name,
)
from app.modules.dbutils.db_users_permission import (
    get_devices_list,
    delete_associate_by_id,
    get_associate_device_group,
    create_associate_device_group,
    check_associate,
    get_all_associate,
)
from app.modules.dbutils.db_user_rights import check_user_role_redirect
from app import logger
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_role_redirect
def associate_settings(user_group_id: int):
    settings_menu_active: bool = True
    logger.info(
        f"User: {session['user']} ({session['rights']}) opens the user settings"
    )
    if request.method == "POST" and request.form.get("add_associate"):
        devices_list: list = request.form.getlist("devices_list")
        if not devices_list:
            flash("Device not selected", "info")
            return redirect(url_for("associate_settings", user_group_id=user_group_id))
        for device_id in devices_list:
            if not check_associate(user_group_id=user_group_id, device_id=device_id):
                result: bool = create_associate_device_group(
                    device_id=device_id,
                    user_group_id=int(user_group_id),
                )
                if not result:
                    flash("Update associate Error", "warning")
                    return redirect(
                        url_for("associate_settings", user_group_id=user_group_id)
                    )

        flash(f"Add association success", "success")
        return redirect(url_for("associate_settings", user_group_id=user_group_id))
    #
    if request.method == "POST" and request.form.get("del_associate_btn"):
        associate_id: int = int(request.form.get(f"del_associate_btn"))
        result: bool = delete_associate_by_id(
            associate_id=associate_id,
        )
        if not result:
            flash("Delete Error", "warning")
            return redirect(url_for("associate_settings", user_group_id=user_group_id))
        flash(f"Delete association success", "success")
        return redirect(url_for("associate_settings", user_group_id=user_group_id))
    #
    if request.method == "POST" and request.form.get("del_all_associate_btn"):
        associate_id_list = get_all_associate(user_group_id=user_group_id)
        if not associate_id_list:
            return redirect(url_for("associate_settings", user_group_id=user_group_id))
        for associate_id in associate_id_list:
            result: bool = delete_associate_by_id(
                associate_id=associate_id,
            )
            if not result:
                flash("Delete Error", "warning")
        flash(f"Delete association success", "success")
        return redirect(url_for("associate_settings", user_group_id=user_group_id))

    return render_template(
        "associate_settings.html",
        settings_menu_active=settings_menu_active,
        associate_user_group=get_associate_device_group(
            user_group_id=int(user_group_id)
        ),
        devices=get_devices_list(),
        groups=get_all_user_group(),
        user_group_name=get_user_group_name(user_group_id=user_group_id),
    )