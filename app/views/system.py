import threading
from flask import jsonify, session
from app import app
from app.modules.auth.auth_users_ldap import check_auth


@app.route("/api/run_backup_now", methods=["POST"])
@check_auth
def run_backup_now():
    if session.get("rights") != "sadmin":
        return jsonify({"error": "Permission denied"}), 403
    # Импорт внутри функции – разрывает циклическую зависимость
    from backuper import run_backup

    thread = threading.Thread(target=run_backup)
    thread.start()
    return jsonify({"status": "started"}), 202
