from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)
from app.modules.dbutils.db_groups import (
    get_user_group,
    add_user_group,
    delete_user_group,
)
from app.modules.dbutils.db_user_rights import check_user_role_redirect
from app import logger
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_role_redirect
def users_groups():
    settings_menu_active: bool = True
    user_groups_active: bool = True
    logger.info(
        f"User: {session['user']} ({session['rights']}) opens the user settings groups page"
    )
    #
    if request.method == "POST" and request.form.get("add_user_group_btn"):
        user_group_name = request.form.get(f"user_group")
        result: bool = add_user_group(
            user_group_name=user_group_name,
        )
        if not result:
            flash("Added group Error", "warning")
            return redirect(url_for("users_groups"))

        flash(f"Group has been added", "success")
        return redirect(url_for("users_groups"))
    #
    if request.method == "POST" and request.form.get("del_user_group_btn"):
        user_group_id = int(request.form.get(f"del_user_group_btn"))
        result: bool = delete_user_group(
            user_group_id=user_group_id,
        )
        if not result:
            flash("Deleting group Error", "warning")
            return redirect(url_for("users_groups"))

        flash(f"Group has been deleted", "success")
        return redirect(url_for("users_groups"))
    return render_template(
        "users_groups.html",
        user_groups_active=user_groups_active,
        settings_menu_active=settings_menu_active,
        user_groups=get_user_group(),
    )
