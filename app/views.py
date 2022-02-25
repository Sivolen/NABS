from app import app

from flask import (
    render_template,
    request,
    flash,
    jsonify,
    session,
    url_for,
    redirect,
)

from modules.login_ldap import LDAP_FLASK, check_auth
from modules.path_helper import search_configs_path

from app.utils import (
    get_last_config_for_device,
    get_all_cfg_timestamp_for_device,
    get_previous_config,
)

search_configs_path = search_configs_path()


# Home page and search devices
@app.route("/", methods=["POST", "GET"])
@check_auth
def index():
    navigation = True
    if request.method == "POST":
        if request.form.get("search_input"):
            ipaddress = request.form.get("search_input")
            check_ip = get_last_config_for_device(ipaddress=ipaddress)
            if check_ip is not None:
                return redirect(f"/diff_page/{ipaddress}")
            else:
                flash("Device not found, check the entered ipaddress", "warning")
                return render_template(
                    "index.html", ipaddress=ipaddress, navigation=navigation
                )
    else:
        return render_template("index.html", navigation=navigation)


# Config compare page
@app.route("/diff_page/<ipaddress>", methods=["POST", "GET"])
@check_auth
def diff_page(ipaddress):
    navigation = True
    config_timestamp = get_all_cfg_timestamp_for_device(ipaddress=ipaddress)
    last_config_dict = get_last_config_for_device(ipaddress=ipaddress)
    if last_config_dict is not None:
        last_config = last_config_dict["last_config"]
        timestamp = last_config_dict["timestamp"]
        return render_template(
            "diff_page.html",
            last_config=last_config,
            navigation=navigation,
            cfg_directories=config_timestamp,
            timestamp=timestamp,
            ipaddress=ipaddress,
        )
    else:
        flash("Device not found?", "info")
        return redirect(url_for("index"))


# Get devices status page
@app.route("/devices", methods=["POST", "GET"])
@check_auth
def devices():
    navigation = True
    return render_template("devices.html", navigation=navigation)


# Authorization form
@app.route("/login", methods=["POST", "GET"])
def login():
    navigation = False
    if "user" not in session or session["user"] == "":
        if request.method == "POST":
            page_email = request.form["email"]
            page_password = request.form["password"]
            ldap_connect = LDAP_FLASK(page_email, page_password)

            if ldap_connect.bind():
                session["user"] = page_email
                flash("You were successfully logged in", "success")
                return redirect(url_for("index"))
            else:
                flash("May be the password is incorrect?", "danger")
                return render_template("login.html", navigation=navigation)
        else:
            return render_template("login.html", navigation=navigation)

    else:
        session["user"] = ""
        flash("You were successfully logged out", "warning")
        return redirect(url_for("login"))


# Ajax function get previous configs for device
@app.route("/previous_config/", methods=["POST", "GET"])
@check_auth
def previous_config():
    if request.method == "POST":
        previous_config_data = request.get_json()
        previous_ipaddress = previous_config_data["ipaddress"]
        previous_timestamp = previous_config_data["date"]
        previous_config_file = get_previous_config(
            ipaddress=previous_ipaddress, db_timestamp=previous_timestamp
        )
        result = "ok"
        if previous_config_file is not None:
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": previous_config_file,
                }
            )
        else:
            result = "none"
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": None,
                }
            )


# Ajax function get devices status
@app.route("/device_status/", methods=["POST", "GET"])
@check_auth
def device_status():
    if request.method == "POST":
        pass


# Ajax function get devices status
@app.route("/restore_config/", methods=["POST", "GET"])
@check_auth
def restore_config():
    if request.method == "POST":
        pass
