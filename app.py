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

from modules.differ import diff_get_context_changed
from web_app.app_helper import *


search_configs_path = search_configs_path()


# Home page and search devices
@app.route("/", methods=["POST", "GET"])
@check_auth
def index():
    navigation = True
    if request.method == "POST":
        if request.form.get("searchdevice"):
            ipaddress = request.form.get("searchdevice")
            check_ip = search_configs_path.get_all_cfg_in_directories_if_exist(
                ipaddress=ipaddress
            )
            if len(check_ip) > 0:
                return redirect(f"/diff_page2/{ipaddress}")
            else:
                flash("Device not found, check the entered ipaddress", "warning")
                return render_template(
                    "..index.html", ipaddress=ipaddress, navigation=navigation
                )
    else:
        return render_template("index.html", navigation=navigation)


@app.route("/mergely", methods=["POST", "GET"])
def mergely():
    navigation = True
    if request.method == "POST":
        pass
    return render_template("mergely.html", navigation=navigation)


# Config compare page
@app.route("/diff_page/<ipaddress>", methods=["POST", "GET"])
@check_auth
def diff_page(ipaddress):
    navigation = True
    directories = search_configs_path.get_all_cfg_in_directories_if_exist(
        ipaddress=ipaddress
    )
    directories.sort(reverse=True)
    last_config_dict = search_configs_path.get_lats_config_for_device(
        ipaddress=ipaddress
    )
    last_date_cfg_directory = last_config_dict["folder"]
    directories.remove(last_date_cfg_directory)
    if request.method == "POST":
        pass
    else:
        last_config = open(last_config_dict["config_path"]).read()
        timestamp = last_config_dict["timestamp"]
        return render_template(
            "diff_page.html",
            last_config=last_config,
            navigation=navigation,
            cfg_directories=directories,
            last_date_cfg_directory=last_date_cfg_directory,
            timestamp=timestamp,
            ipaddress=ipaddress,
        )


# Config compare page
@app.route("/diff_page2/<ipaddress>", methods=["POST", "GET"])
@check_auth
def diff_page2(ipaddress):
    navigation = True
    directories = get_all_cfg_for_ipaddress(ipaddress=ipaddress)

    last_config_dict = get_last_config_for_device(ipaddress=ipaddress)
    print(last_config_dict)
    # print(last_config_dict)
    # last_date_cfg_directory = last_config_dict["timestamp"]
    # directories.remove(last_date_cfg_directory)
    if request.method == "POST":
        pass
    else:
        if last_config_dict is not None:
            last_config = last_config_dict["last_config"]
            timestamp = last_config_dict["timestamp"]
            return render_template(
                "diff_page.html",
                last_config=last_config,
                navigation=navigation,
                cfg_directories=directories,
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
    if request.method == "POST":
        pass
    else:
        return render_template("devices.html", navigation=navigation)


# Authorization form
@app.route("/login", methods=["POST", "GET"])
def login():
    navigation = False
    if "user" not in session or session["user"] == "":
        if request.method == "POST":
            if request.form["submit-btn"] == "login-btn":
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
            elif request.form["submit-btn"] == "signin-btn":
                print("signin")
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
        previous_config_path = search_configs_path.get_config_path(
            directory_name=previous_config_data["date"],
            file_name=previous_config_data["ipaddress"],
        )
        last_config_path = search_configs_path.get_lats_config_for_device(
            ipaddress=previous_config_data["ipaddress"]
        )
        if Path(f"{previous_config_path}.cfg").is_file():
            last_config_file = open(last_config_path["config_path"], "r")
            previous_config_file = open(f"{previous_config_path}.cfg", "r")
            result = diff_get_context_changed(
                config1=previous_config_file.readlines(),
                config2=last_config_file.readlines(),
            )
            previous_config_file = open(f"{previous_config_path}.cfg", "r").read()
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": previous_config_file,
                }
            )
        else:
            return jsonify(
                {
                    "status": "none",
                }
            )


# Ajax function get previous configs for device
@app.route("/previous_config2/", methods=["POST", "GET"])
@check_auth
def previous_config2():
    if request.method == "POST":
        previous_config_data = request.get_json()
        # previous_config_path = search_configs_path.get_config_path(
        #     directory_name=previous_config_data["date"],
        #     file_name=previous_config_data["ipaddress"],
        # )
        # last_config_path = search_configs_path.get_lats_config_for_device(
        #     ipaddress=previous_config_data["ipaddress"]
        # )
        # if Path(f"{previous_config_path}.cfg").is_file():
        #     last_config_file = open(last_config_path["config_path"], "r")
        #     previous_config_file = open(f"{previous_config_path}.cfg", "r")
        #     result = diff_get_context_changed(
        #         config1=previous_config_file.readlines(),
        #         config2=last_config_file.readlines(),
        #     )
        previous_ipaddress = previous_config_data["ipaddress"]
        previous_timestamp = previous_config_data["date"]
        print(previous_config_data)
        previous_config_file = get_previous_config(ipaddress=previous_ipaddress, db_timestamp=previous_timestamp)
        result = 'ok'
        return jsonify(
            {
                "status": result,
                "previous_config_file": previous_config_file,
            }
        )
    else:
        return jsonify(
            {
                "status": "none",
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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
