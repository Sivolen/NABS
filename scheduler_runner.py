#!/usr/bin/env python
import sys
import time
import logging
from pathlib import Path

# Добавляем путь к проекту для импорта
sys.path.insert(0, "/opt/NABS")

from app import app
from app.modules.dbutils.db_scheduler import update_scheduler_heartbeat
from config import SCHEDULER_TIMEZONE
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Настройка логирования ---
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
    """Задача, которая выполняется по расписанию."""
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
    """Читает настройки расписания из БД и возвращает словарь с триггером."""
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


# ----------------------------------------------------------------------
def main():
    # Настройка хранилища заданий в PostgreSQL
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if "sslmode" not in db_url:
        db_url += "?sslmode=disable"
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    scheduler = BackgroundScheduler(jobstores=jobstores, timezone=SCHEDULER_TIMEZONE)

    # Загружаем и добавляем задачу при старте
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
        # После добавления задачи (и до старта планировщика) next_run_time может быть None,
        # но после scheduler.start() он появится. Поэтому пока не выводим.
    else:
        logger.info("No active job")

    scheduler.start()
    logger.info("Scheduler started")

    # Теперь планировщик запущен, можно получить следующее время выполнения
    job = scheduler.get_job(JOB_ID)
    if job:
        try:
            next_run = job.next_run_time
            if next_run:
                # Приводим к локальному времени (уже в зоне, заданной в конфиге)
                logger.info(f"Job next run time: {next_run}")
            else:
                logger.warning("Job next run time is None (one-time job?)")
        except AttributeError:
            logger.warning("Job.next_run_time not available (APScheduler version < 3.0?)")
    else:
        logger.warning("No job found after scheduler start")

    # Первоначальный heartbeat
    with app.app_context():
        update_scheduler_heartbeat()

    last_settings_hash = None

    # Основной цикл: раз в минуту обновляем heartbeat и проверяем, не изменились ли настройки
    try:
        while True:
            time.sleep(60)
            with app.app_context():
                update_scheduler_heartbeat()

            new_config = load_job()
            current_job = scheduler.get_job(JOB_ID)

            # Вычисляем хэш текущих настроек
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
                    # Выводим новое время запуска
                    job = scheduler.get_job(JOB_ID)
                    if job and job.next_run_time:
                        logger.info(f"Job next run time: {job.next_run_time}")
                elif new_config is not None and current_job:
                    # Параметры изменились — пересоздаём задачу
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
