from app import app
from app.modules.dbutils.db_scheduler import (
    get_scheduler_settings,
    get_scheduler_heartbeat,
)
from datetime import datetime, timedelta, timezone


def update_scheduler_job():
    # Не используется при отдельном процессе
    pass


def is_scheduler_running() -> bool:
    try:
        heartbeat = get_scheduler_heartbeat()
        if not heartbeat or not heartbeat.get("last_seen"):
            return False
        last_seen = heartbeat["last_seen"]
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if (now - last_seen) < timedelta(minutes=2):
            return True
        return False
    except Exception:
        return False


def get_scheduler_status():
    with app.app_context():
        settings = get_scheduler_settings()
        scheduler_active = is_scheduler_running()
        return {
            "is_enabled": settings.is_enabled if settings else False,
            "trigger_type": settings.trigger_type if settings else "interval",
            "interval_seconds": settings.interval_seconds if settings else 3600,
            "cron_expression": settings.cron_expression if settings else "0 2 * * *",
            "scheduler_running": scheduler_active,
        }


def get_scheduler_full_status():
    with app.app_context():
        settings = get_scheduler_settings()
        enabled = settings.is_enabled if settings else False
        running = is_scheduler_running()
        return {"enabled": enabled, "running": running, "active": enabled and running}
