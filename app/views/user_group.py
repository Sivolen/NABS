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
)
from app.modules.dbutils.db_users_permission import (
    get_associate_user_group,
    create_associate_user_group,
    delete_associate_user_group,

)
from app.modules.dbutils.db_user_rights import check_user_role_redirect
from app import logger
from app.modules.auth.auth_users_local import AuthUsers
from app.modules.auth.auth_users_ldap import check_auth

@check_auth
@check_user_role_redirect
def user_group(user_id: int):
    settings_menu_active: bool = True
    logger.info(
        f"User: {session['user']} ({session['rights']}) opens the user user group"
    )
    if request.method == "POST" and request.form.get("add_associate_user_group_btn"):
        user_group_id = request.form.get(f"user_group_name")
        result = create_associate_user_group(
            user_group_id=int(user_group_id),
            user_id=int(user_id),
        )
        if not result:
            flash("Update Error", "warning")
            return redirect(url_for("user_group", user_id=user_id))
        flash(f"Add association success", "success")
        return redirect(url_for("user_group", user_id=user_id))
        #
    if request.method == "POST" and request.form.get("del_group_associate_btn"):
        user_group_id = request.form.get(f"del_group_associate_btn")

        result = delete_associate_user_group(
            associate_id=int(user_group_id),
        )
        if not result:
            flash("Delete Error", "warning")
            return redirect(url_for("user_group", user_id=user_id))
        flash(f"Delete association success", "success")
        return redirect(url_for("user_group", user_id=user_id))
    #
    auth_user = AuthUsers
    return render_template(
        "user_group.html",
        settings_menu_active=settings_menu_active,
        associate_user_group=get_associate_user_group(user_id=int(user_id)),
        user_group=get_all_user_group(),
        user_email=auth_user(user_id=user_id).get_user_email_by_id(),
    )