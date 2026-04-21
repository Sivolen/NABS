"""
Module for scheduler status management (used by web UI).
Does not interact with the scheduler process directly; relies on database heartbeat.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from app import app
from app.modules.dbutils.db_scheduler import (
    get_scheduler_settings,
    get_scheduler_heartbeat,
)

logger = logging.getLogger(__name__)


def update_scheduler_job() -> None:
    """
    Placeholder function for compatibility.
    In the standalone scheduler architecture, this does nothing.
    """
    pass


def is_scheduler_running() -> bool:
    """
    Determines if the scheduler process is considered running based on heartbeat.
    Returns True if the last heartbeat was updated within the last 2 minutes.
    """
    try:
        heartbeat = get_scheduler_heartbeat()
        if not heartbeat or not heartbeat.get("last_seen"):
            logger.debug("No heartbeat record found")
            return False

        last_seen = heartbeat["last_seen"]
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        running = (now - last_seen) < timedelta(minutes=2)
        if not running:
            logger.debug(f"Heartbeat too old: {now - last_seen}")
        return running
    except Exception as e:
        logger.error(f"Error checking scheduler status: {e}", exc_info=True)
        return False


def get_scheduler_status() -> Dict[str, Any]:
    """
    Returns the current scheduler status including database settings and running state.
    Used by the web UI.
    """
    with app.app_context():
        settings = get_scheduler_settings()
        if settings is None:
            logger.warning("Scheduler settings not found in DB, using defaults")
            return {
                "is_enabled": False,
                "trigger_type": "interval",
                "interval_seconds": 3600,
                "cron_expression": "0 2 * * *",
                "scheduler_running": False,
            }

        scheduler_active = is_scheduler_running()
        return {
            "is_enabled": settings.is_enabled,
            "trigger_type": settings.trigger_type,
            "interval_seconds": settings.interval_seconds,
            "cron_expression": settings.cron_expression,
            "scheduler_running": scheduler_active,
        }


def get_scheduler_full_status() -> Dict[str, Any]:
    """
    Returns a simplified status for API endpoints (e.g., /api/scheduler_status).
    """
    with app.app_context():
        settings = get_scheduler_settings()
        enabled = settings.is_enabled if settings else False
        running = is_scheduler_running()
        return {"enabled": enabled, "running": running, "active": enabled and running}
