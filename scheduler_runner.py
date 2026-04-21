#!/usr/bin/env python
"""
Scheduler runner for NABS.
Runs as a standalone systemd service and manages backup jobs.
"""

import atexit
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from app.modules.dbutils.db_scheduler import update_scheduler_heartbeat
from app.models import SchedulerHeartbeat
from config import SCHEDULER_TIMEZONE
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# --- Logging setup ------------------------------------------------------------
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "nabs-scheduler.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
)
logger = logging.getLogger("scheduler")

JOB_ID = "backup_job"


# -----------------------------------------------------------------------------
def scheduled_backup() -> None:
    """Task executed by the scheduler."""
    logger.info("=== scheduled_backup triggered ===")
    try:
        with app.app_context():
            from backuper import run_backup

            run_backup()
    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True)
    logger.info("=== scheduled_backup finished ===")


# -----------------------------------------------------------------------------
def load_job_config() -> Optional[Dict[str, Any]]:
    """
    Reads scheduler settings from the database and returns a configuration dict.

    Returns:
        - For interval: {'trigger': 'interval', 'seconds': int}
        - For cron: {'trigger': CronTrigger instance}
        - None if scheduler is disabled or no settings found.
    """
    from app.models import SchedulerSettings

    with app.app_context():
        settings = SchedulerSettings.query.first()
        if not settings or not settings.is_enabled:
            logger.info("Scheduler disabled in DB")
            return None

        if settings.trigger_type == "interval":
            return {"trigger": "interval", "seconds": settings.interval_seconds}

        # No else – direct return
        cron_trigger = CronTrigger.from_crontab(settings.cron_expression)
        return {"trigger": cron_trigger}


# -----------------------------------------------------------------------------
def cleanup_heartbeat() -> None:
    """Removes the heartbeat record from the database (called on shutdown)."""
    with app.app_context():
        heartbeat = SchedulerHeartbeat.query.first()
        if not heartbeat:
            return
        db.session.delete(heartbeat)
        db.session.commit()
        logger.info("Heartbeat record removed on shutdown.")


# -----------------------------------------------------------------------------
def create_scheduler() -> BackgroundScheduler:
    """Creates and configures the APScheduler instance."""
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if "sslmode" not in db_url:
        db_url += "?sslmode=disable"
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    return BackgroundScheduler(jobstores=jobstores, timezone=SCHEDULER_TIMEZONE)


# -----------------------------------------------------------------------------
def add_job_to_scheduler(
    scheduler: BackgroundScheduler, config: Dict[str, Any]
) -> None:
    """Adds the backup job to the scheduler."""
    trigger = config["trigger"]
    if trigger == "interval":
        trigger = IntervalTrigger(seconds=config["seconds"])
    scheduler.add_job(
        id=JOB_ID,
        func=scheduled_backup,
        trigger=trigger,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Job added to scheduler")


# -----------------------------------------------------------------------------
def log_next_run_time(scheduler: BackgroundScheduler) -> None:
    """Logs the next execution time of the job."""
    job = scheduler.get_job(JOB_ID)
    if not job:
        logger.warning("No job found after scheduler start")
        return

    try:
        next_run = job.next_run_time
        if next_run:
            logger.info(f"Job next run time: {next_run}")
            return
        logger.warning("Job next run time is None (one-time job?)")
    except AttributeError:
        logger.warning("Job.next_run_time not available (APScheduler version < 3.0?)")


# -----------------------------------------------------------------------------
def cleanup_old_heartbeats() -> None:
    """Removes heartbeat records older than 5 minutes."""
    with app.app_context():
        old = datetime.now(timezone.utc) - timedelta(minutes=5)
        deleted = SchedulerHeartbeat.query.filter(
            SchedulerHeartbeat.last_seen < old
        ).delete()
        if deleted:
            logger.info(f"Deleted {deleted} stale heartbeat record(s)")
        db.session.commit()


# -----------------------------------------------------------------------------
def update_heartbeat() -> None:
    """Updates the heartbeat record in the database."""
    with app.app_context():
        update_scheduler_heartbeat()


# -----------------------------------------------------------------------------
def compute_config_hash(config: Optional[Dict[str, Any]]) -> Optional[int]:
    """Computes a hash of the scheduler configuration for change detection."""
    if config is None:
        return None
    if config["trigger"] == "interval":
        return hash(("interval", config.get("seconds")))
    # For cron trigger, use string representation
    return hash(("cron", str(config["trigger"])))


# -----------------------------------------------------------------------------
def update_job_if_needed(
    scheduler: BackgroundScheduler,
    new_config: Optional[Dict[str, Any]],
    last_hash: Optional[int],
) -> Optional[int]:
    """Recreates the job if the configuration has changed."""
    current_hash = compute_config_hash(new_config)
    if current_hash == last_hash:
        return last_hash

    # Configuration changed
    if new_config is None:
        if scheduler.get_job(JOB_ID):
            scheduler.remove_job(JOB_ID)
            logger.info("Job removed (disabled)")
        return current_hash

    # Add or replace job
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
        logger.info("Job recreated (settings changed)")
    add_job_to_scheduler(scheduler, new_config)
    log_next_run_time(scheduler)
    return current_hash


# -----------------------------------------------------------------------------
def main() -> None:
    """Main entry point."""
    scheduler = create_scheduler()

    # Initial job setup
    job_config = load_job_config()
    if job_config:
        add_job_to_scheduler(scheduler, job_config)
    else:
        logger.info("No active job")

    scheduler.start()
    atexit.register(cleanup_heartbeat)
    logger.info("Scheduler started")

    log_next_run_time(scheduler)

    cleanup_old_heartbeats()
    update_heartbeat()

    last_config_hash = compute_config_hash(job_config)

    try:
        while True:
            time.sleep(60)
            cleanup_old_heartbeats()
            update_heartbeat()
            new_config = load_job_config()
            last_config_hash = update_job_if_needed(
                scheduler, new_config, last_config_hash
            )
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler shut down")


if __name__ == "__main__":
    main()
