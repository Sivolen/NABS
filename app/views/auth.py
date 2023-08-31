from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)

from app.modules.dbutils.db_users_permission import get_users_group

from app.modules.dbutils.db_user_rights import check_user_rights

from app.modules.auth.auth_users_local import AuthUsers

from app.modules.auth.auth_users_ldap import LdapFlask


# Authorization form
def login():
    """
    This function render authorization page
    """
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
                    return render_template(
                        "login.html",
                    )
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
                    return render_template(
                        "login.html",
                    )
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

    return render_template(
        "login.html",
    )
