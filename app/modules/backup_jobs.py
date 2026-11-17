"""Background single-device polls. Results are visible to every web worker."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from uuid import uuid4

from app import app, db, logger
from app.models import DeviceBackupJob, Devices
from app.modules.backuper import backup_config_on_db

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="device-backup")
_slots = BoundedSemaphore(12)
PENDING_STATES = ("queued", "running")


def job_deadline():
    return datetime.now(timezone.utc) - timedelta(hours=1)


def job_is_pending(job):
    if job is None or job.state not in PENDING_STATES:
        return False
    return job.updated_at.replace(tzinfo=timezone.utc) > job_deadline()


def _update_job(device_id, token, state, error=None):
    updated = DeviceBackupJob.query.filter_by(device_id=device_id, token=token).update(
        dict(state=state, updated_at=datetime.now(timezone.utc), error=error)
    )
    db.session.commit()
    return updated == 1


def _run_job(device_id, token):
    try:
        with app.app_context():
            if not _update_job(device_id, token, "running"):
                return
            try:
                device = db.session.get(Devices, device_id)
                if device is None or not device.is_enabled:
                    result = {"connection_status": "Device disabled or removed"}
                else:
                    ip, driver = device.device_ip, device.connection_driver
                    db.session.rollback()
                    result = backup_config_on_db(napalm_driver=driver, ipaddress=ip)
                status = (result or {}).get(
                    "connection_status"
                ) or "Backup returned no result"
                state = "finished" if status == "Ok" else "failed"
                _update_job(
                    device_id,
                    token,
                    state,
                    None if state == "finished" else str(status),
                )
            except Exception:
                db.session.rollback()
                logger.exception("Single backup failed for device %s", device_id)
                _update_job(
                    device_id, token, "failed", "Backup failed. Check the server log."
                )
    finally:
        _slots.release()


def queue_device_backup(device_id):
    device = Devices.query.filter_by(id=device_id).with_for_update().first()
    if not device or not device.is_enabled:
        db.session.rollback()
        return False, "Device disabled or removed"
    job = db.session.get(DeviceBackupJob, device_id)
    if job_is_pending(job):
        db.session.rollback()
        return True, None
    if not _slots.acquire(blocking=False):
        db.session.rollback()
        return False, "Backup queue is full. Try again shortly."
    token = uuid4().hex
    try:
        if job is None:
            job = DeviceBackupJob(device_id=device_id)
            db.session.add(job)
        job.token = token
        job.state = "queued"
        job.updated_at = datetime.now(timezone.utc)
        job.error = None
        db.session.commit()
        _executor.submit(_run_job, device_id, token)
    except Exception:
        _slots.release()
        db.session.rollback()
        logger.exception("Could not queue backup for device %s", device_id)
        _update_job(device_id, token, "failed", "Could not start backup")
        return False, "Could not start backup"
    return True, None
