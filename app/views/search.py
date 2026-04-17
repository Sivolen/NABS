from flask import render_template, request, flash, session, redirect, url_for, jsonify
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_search import search_in_db


@check_auth
def search():
    search_menu_active = True

    if request.method == "POST":
        request_data = request.form.get("search_input", "").strip()
        if not request_data:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"error": "Request cannot be empty"}), 400
            flash("Request cannot be empty", "warning")
            return redirect(url_for("search"))

        response_data = search_in_db(
            request_data=request_data, user_id=int(session["user_id"])
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            # AJAX запрос: возвращаем JSON
            if response_data:
                return jsonify({"success": True, "data": response_data})
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"No results found for '{request_data}'",
                        }
                    ),
                    404,
                )

        # Обычный POST (без AJAX) – для обратной совместимости
        if not response_data:
            flash(f"No results found for '{request_data}'", "info")
            return redirect(url_for("search"))
        return render_template(
            "search.html",
            search_menu_active=search_menu_active,
            response_data=response_data,
        )

    # GET запрос
    return render_template("search.html", search_menu_active=search_menu_active)
