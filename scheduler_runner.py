#!/usr/bin/env python
import atexit
import os
import sys
import time
import logging
from pathlib import Path

# Add the path to the project for import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from app.modules.dbutils.db_scheduler import update_scheduler_heartbeat
from app.models import SchedulerHeartbeat
from config import SCHEDULER_TIMEZONE
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Logging settings ---
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "nabs-scheduler.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("scheduler")

JOB_ID = "backup_job"


# ----------------------------------------------------------------------
def scheduled_backup():
    """A task that runs on a schedule."""
    logger.info("=== scheduled_backup triggered ===")
    try:
        with app.app_context():
            from backuper import run_backup

            run_backup()
    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True)
    logger.info("=== scheduled_backup finished ===")


# ----------------------------------------------------------------------
def load_job():
    """Reads schedule settings from the database and returns a dictionary with the trigger."""
    from app.models import SchedulerSettings

    with app.app_context():
        settings = SchedulerSettings.query.first()
        if not settings or not settings.is_enabled:
            logger.info("Scheduler disabled in DB")
            return None
        if settings.trigger_type == "interval":
            return {
                "trigger": "interval",
                "seconds": settings.interval_seconds,
            }
        else:
            return {
                "trigger": CronTrigger.from_crontab(settings.cron_expression),
            }


def cleanup_heartbeat():
    with app.app_context():
        heartbeat = SchedulerHeartbeat.query.first()
        if heartbeat:
            db.session.delete(heartbeat)
            db.session.commit()
            logger.info("Heartbeat record removed on shutdown.")


# ----------------------------------------------------------------------
def main():
    # Setting up job storage in PostgresSQL
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if "sslmode" not in db_url:
        db_url += "?sslmode=disable"
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    scheduler = BackgroundScheduler(jobstores=jobstores, timezone=SCHEDULER_TIMEZONE)

    # Load and add the task at startup
    job_config = load_job()
    if job_config:
        scheduler.add_job(
            id=JOB_ID,
            func=scheduled_backup,
            trigger=job_config["trigger"],
            seconds=job_config.get("seconds"),
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Job added")
    else:
        logger.info("No active job")

    scheduler.start()
    atexit.register(cleanup_heartbeat)
    logger.info("Scheduler started")

    job = scheduler.get_job(JOB_ID)
    if job:
        try:
            next_run = job.next_run_time
            if next_run:
                logger.info(f"Job next run time: {next_run}")
            else:
                logger.warning("Job next run time is None (one-time job?)")
        except AttributeError:
            logger.warning(
                "Job.next_run_time not available (APScheduler version < 3.0?)"
            )
    else:
        logger.warning("No job found after scheduler start")

    # Первоначальный heartbeat
    with app.app_context():
        update_scheduler_heartbeat()

    last_settings_hash = None

    # Main loop: update heartbeat once a minute and check if the settings have changed
    try:
        while True:
            time.sleep(60)
            with app.app_context():
                from datetime import datetime, timedelta, timezone
                # Удаляем старые записи heartbeat (старше 5 минут)
                old = datetime.now(timezone.utc) - timedelta(minutes=5)
                SchedulerHeartbeat.query.filter(SchedulerHeartbeat.last_seen < old).delete()
                db.session.commit()
                # Создаём свежую запись
                update_scheduler_heartbeat()

            new_config = load_job()
            current_job = scheduler.get_job(JOB_ID)

            # Calculate the hash of the current settings
            if new_config:
                if new_config["trigger"] == "interval":
                    current_hash = hash(("interval", new_config.get("seconds")))
                else:
                    current_hash = hash(("cron", str(new_config["trigger"])))
            else:
                current_hash = None

            if current_hash != last_settings_hash:
                last_settings_hash = current_hash
                if new_config is None and current_job:
                    scheduler.remove_job(JOB_ID)
                    logger.info("Job removed (disabled)")
                elif new_config is not None and current_job is None:
                    scheduler.add_job(
                        id=JOB_ID,
                        func=scheduled_backup,
                        trigger=new_config["trigger"],
                        seconds=new_config.get("seconds"),
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                    )
                    logger.info("Job added (enabled)")
                    # Display the new launch time
                    job = scheduler.get_job(JOB_ID)
                    if job and job.next_run_time:
                        logger.info(f"Job next run time: {job.next_run_time}")
                elif new_config is not None and current_job:
                    # Parameters have changed - recreate the task
                    scheduler.remove_job(JOB_ID)
                    scheduler.add_job(
                        id=JOB_ID,
                        func=scheduled_backup,
                        trigger=new_config["trigger"],
                        seconds=new_config.get("seconds"),
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                    )
                    logger.info("Job recreated (settings changed)")
                    job = scheduler.get_job(JOB_ID)
                    if job and job.next_run_time:
                        logger.info(f"Job next run time: {job.next_run_time}")
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler shut down")


# ----------------------------------------------------------------------
if __name__ == "__main__":
    main()
