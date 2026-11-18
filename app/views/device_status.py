import traceback
from flask import (
    request,
    jsonify,
    session,
)

from app import db, logger
from app.models import DeviceBackupJob
from app.modules.backup_jobs import job_is_pending, queue_device_backup
from app.modules.backup_service import run_backup_config_on_db
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.access import can_access_device
from app.modules.dbutils.db_devices import get_device_is_enabled, get_device_id
from app.modules.dbutils.db_utils import get_device_row_state
from app.modules.dbutils.db_validation import get_device_validation_status


# Ajax function to check device status
@check_auth
def device_status():
    if request.method != "POST":
        return jsonify({"status": "error", "message": "Method not allowed"}), 405

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": False, "error": "No data provided"}), 400

        device_ip = data.get("device")
        if not device_ip:
            return jsonify({"status": False, "error": "Device IP missing"}), 400

        # Получаем device_id и is_enabled
        device_id_row = get_device_id(ipaddress=device_ip)
        if not device_id_row:
            return jsonify({"status": False, "error": "Device not found"}), 404
        device_id = device_id_row[0]
        if not can_access_device(session, device_id):
            return jsonify({"status": False, "error": "Access denied"}), 403
        is_enabled = get_device_is_enabled(device_id)

        if not is_enabled:
            return jsonify(
                {
                    **get_device_row_state(device_id),
                    "status": True,
                    "device_ip": device_ip,
                    "connection_status": "Device disabled",
                }
            )

        # Вызов бэкапа
        result_dict = run_backup_config_on_db(data)
        if result_dict is None:
            return jsonify({"status": False, "error": "Backup returned None"}), 500

        if result_dict.get("skipped"):
            return (
                jsonify({"status": False, "error": result_dict["connection_status"]}),
                409,
            )

        validation = get_device_validation_status(device_id)
        validation_id = validation.id if validation else None
        validation_status = validation.status if validation else None

        return jsonify(
            {
                "status": True,
                **get_device_row_state(device_id),
                "device_ip": device_ip,
                "validation_id": validation_id,
                "validation_status": validation_status,
            }
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Device status error: {error_msg}\n{traceback.format_exc()}")
        return jsonify({"status": False, "error": f"Backup error: {error_msg}"}), 200


@check_auth
def device_backup_job(device_id):
    if not can_access_device(session, device_id):
        return jsonify({"error": "Access denied"}), 403

    if request.method == "POST":
        accepted, error = queue_device_backup(device_id)
        if not accepted:
            return jsonify({"error": error}), 409
        return jsonify({"state": "pending"}), 202

    job = db.session.get(DeviceBackupJob, device_id)
    if job is None:
        return jsonify({"error": "No backup job found"}), 404
    if job_is_pending(job):
        return jsonify({"state": "pending", "phase": job.state})
    state = "finished" if job.state == "finished" else "failed"
    validation = get_device_validation_status(device_id)
    return jsonify(
        {
            **get_device_row_state(device_id),
            "state": state,
            "error": None
            if state == "finished"
            else job.error or "Backup was interrupted or timed out",
            "validation_id": validation.id if validation else None,
            "validation_status": validation.status if validation else None,
        }
    )
