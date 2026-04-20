# app/views/logs.py
import os
from flask import render_template, request, send_file, abort, session
from app import app
from app.modules.auth.auth_users_ldap import check_auth

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
)
ALLOWED_LOGS = ["log.log", "app_log.log", "nabs-scheduler.log"]


@app.route("/logs", methods=["GET", "POST"])
@check_auth
def view_logs():
    if session.get("rights") != "sadmin":
        abort(403)

    selected_log = request.args.get("log", "app_log.log")
    if selected_log not in ALLOWED_LOGS:
        selected_log = "app_log.log"

    log_path = os.path.join(LOG_DIR, selected_log)
    log_content = ""
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()

    return render_template(
        "logs.html",
        log_content=log_content,
        selected_log=selected_log,
        allowed_logs=ALLOWED_LOGS,
    )


@app.route("/logs/download")
@check_auth
def download_log():
    if session.get("rights") != "sadmin":
        abort(403)

    log_name = request.args.get("log", "app_log.log")
    if log_name not in ALLOWED_LOGS:
        abort(404)
    log_path = os.path.join(LOG_DIR, log_name)
    if not os.path.exists(log_path):
        abort(404)
    return send_file(log_path, as_attachment=True, download_name=log_name)
