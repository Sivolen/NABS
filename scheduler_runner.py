#!/usr/bin/env python
import sys
import time
import logging

from app.modules.dbutils.db_scheduler import update_scheduler_heartbeat
from config import SCHEDULER_TIMEZONE

sys.path.insert(0, "/opt/NABS")
from app import app
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("/var/log/nabs-scheduler.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("scheduler")

JOB_ID = "backup_job"


def scheduled_backup():
    logger.info("=== scheduled_backup triggered ===")
    try:
        with app.app_context():
            from backuper import run_backup
            run_backup()
    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True)
    logger.info("=== scheduled_backup finished ===")


def load_job(scheduler):
    # Read settings from BD
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
                "next_run_time": None,
            }
        else:
            return {
                "trigger": CronTrigger.from_crontab(settings.cron_expression),
                "next_run_time": None,
            }


def main():
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if "sslmode" not in db_url:
        db_url += "?sslmode=disable"
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    scheduler = BackgroundScheduler(jobstores=jobstores, timezone=SCHEDULER_TIMEZONE)

    # Load task after starts
    job_config = load_job(scheduler)
    job = scheduler.get_job(JOB_ID)
    if job and job.next_run_time:
        logger.info(f"Job next run time: {job.next_run_time} (local: {job.next_run_time.astimezone()})")
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
    logger.info("Scheduler started")
    with app.app_context():
        # first start task
        update_scheduler_heartbeat()
    last_settings_hash = None

    # Reload settings every 60 seconds
    try:
        while True:
            time.sleep(60)
            with app.app_context():
                update_scheduler_heartbeat()

            new_config = load_job(scheduler)
            current_job = scheduler.get_job(JOB_ID)

            # Вычисляем хэш текущих настроек
            if new_config:
                if new_config["trigger"] == "interval":
                    current_hash = hash(("interval", new_config.get("seconds")))
                else:
                    # For the cron trigger we use a string representation
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
                elif new_config is not None and current_job:
                    # Update the task only if the parameters have changed
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
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
