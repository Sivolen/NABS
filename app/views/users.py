from flask import (
    render_template,
    request,
    flash,
    url_for,
    redirect,
)
from app.modules.dbutils.db_groups import (
    get_all_devices_group,
    get_user_group,
)
from app.modules.dbutils.db_user_roles import (
    create_user_role,
    delete_user_role,
    get_user_roles,
)
from app.modules.dbutils.db_user_rights import check_user_role_redirect
from app.modules.auth.auth_users_local import AuthUsers
from app.modules.auth.auth_users_ldap import check_auth
from config import auth_methods


# NABS settings route
@check_auth
@check_user_role_redirect
def users():
    """
    This function render settings page
    """
    settings_menu_active: bool = True
    users_active: bool = True
    auth_users = AuthUsers
    if request.method == "POST" and request.form.get("edit_user_btn"):
        user_id = request.form.get(f"edit_user_btn")
        page_data = {
            "user_id": user_id,
            "username": request.form.get(f"username_{user_id}"),
            "email": request.form.get(f"email_{user_id}"),
            "role": request.form.get(f"role_{user_id}"),
            "password": request.form.get(f"password_{user_id}"),
            "auth_method": request.form.get(f"auth_method_{user_id}"),
        }
        result: bool = auth_users(**page_data).update_user()

        if not result:
            flash("Update Error", "warning")
            return redirect(url_for("users"))

        flash(f"User {page_data['username']} has been updated", "success")
        return redirect(url_for("users"))
    #
    if request.method == "POST" and request.form.get("del_user_btn"):
        user_id = request.form.get(f"del_user_btn")
        result: bool = auth_users(user_id=user_id).del_user()
        if not result:
            flash("delete Error", "warning")
            return redirect(url_for("users"))

        flash(f"User has been deleted", "success")
        return redirect(url_for("users"))
    #
    if request.method == "POST" and request.form.get("add_user_btn"):
        page_data = {
            "username": request.form.get(f"username"),
            "email": request.form.get(f"email"),
            "role": request.form.get(f"role"),
            "password": request.form.get(f"password"),
            "auth_method": request.form.get(f"auth_method"),
        }
        result: bool = auth_users(**page_data).add_user()
        if not result:
            flash("Added Error", "warning")
            return redirect(url_for("users"))

        flash(f"User has been added", "success")
        return redirect(url_for("users"))
    #
    if request.method == "POST" and request.form.get("add_role_btn"):
        role_name = request.form.get(f"role")
        result: bool = create_user_role(
            role_name=role_name,
        )
        if not result:
            flash("Added role Error", "warning")
            return redirect(url_for("users"))
        flash(f"Role has been added", "success")
        return redirect(url_for("users"))
    #
    if request.method == "POST" and request.form.get("del_role_btn"):
        role_id = int(request.form.get(f"del_role_btn"))
        result: bool = delete_user_role(
            role_id=role_id,
        )
        if not result:
            flash("Deleting role Error", "warning")
            return redirect(url_for("users"))

        flash(f"Role has been deleted", "success")
        return redirect(url_for("users"))
    #
    return render_template(
        "users.html",
        users_list=auth_users.get_users_list(),
        groups=get_all_devices_group(),
        users_active=users_active,
        user_roles=get_user_roles(),
        user_groups=get_user_group(),
        auth_methods=auth_methods,
        settings_menu_active=settings_menu_active,
    )
