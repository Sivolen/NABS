from flask import (
    render_template,
    request,
    flash,
    session,
    redirect,
    url_for,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_search import search_in_db


@check_auth
def search():
    """
    Function for search
    """
    search_menu_active = True
    if request.method == "POST" and not request.form.get("search_input"):
        flash(f"Request cannot be empty", "warning")
        return redirect(url_for("search"))
    #
    if request.method == "POST" and request.form.get("search_input"):
        request_data = request.form.get("search_input")
        response_data = search_in_db(
            request_data=str(request_data), user_id=int(session["user_id"])
        )
        return render_template(
            "search.html",
            search_menu_active=search_menu_active,
            response_data=response_data,
        )
    #
    return render_template(
        "search.html",
        search_menu_active=search_menu_active,
    )
