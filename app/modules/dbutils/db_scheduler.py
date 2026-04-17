# app/modules/dbutils/db_scheduler.py
from datetime import datetime, timezone
from app.models import SchedulerSettings, db, SchedulerHeartbeat
from app import logger


def get_scheduler_settings() -> SchedulerSettings | None:
    """Возвращает настройки планировщика или None."""
    try:
        return SchedulerSettings.query.first()
    except Exception as e:
        logger.error(f"Failed to get scheduler settings: {e}")
        return None


def update_scheduler_settings(
    is_enabled, trigger_type, interval_seconds, cron_expression
) -> bool:
    """Обновляет или создаёт настройки планировщика."""
    try:
        settings = SchedulerSettings.query.first()
        if not settings:
            settings = SchedulerSettings()
            db.session.add(settings)
        settings.is_enabled = is_enabled
        settings.trigger_type = trigger_type
        settings.interval_seconds = interval_seconds
        settings.cron_expression = cron_expression
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update scheduler settings: {e}")
        return False


def init_default_scheduler_settings() -> None:
    """Создаёт запись с настройками по умолчанию, если её нет."""
    try:
        if not SchedulerSettings.query.first():
            default = SchedulerSettings()
            db.session.add(default)
            db.session.commit()
            logger.info("Default scheduler settings created.")
    except Exception as e:
        logger.error(f"Failed to init default scheduler settings: {e}")


def update_scheduler_heartbeat(status: str = "running") -> bool:
    try:
        heartbeat = SchedulerHeartbeat.query.first()
        if not heartbeat:
            heartbeat = SchedulerHeartbeat()
            db.session.add(heartbeat)
        heartbeat.last_seen = datetime.now(timezone.utc)
        heartbeat.status = status
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update scheduler heartbeat: {e}")
        return False


def get_scheduler_heartbeat() -> dict | None:
    try:
        heartbeat = SchedulerHeartbeat.query.first()
        if not heartbeat:
            return None
        return {"last_seen": heartbeat.last_seen, "status": heartbeat.status}
    except Exception as e:
        logger.error(f"Failed to get scheduler heartbeat: {e}")
        return None
