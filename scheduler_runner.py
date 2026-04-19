#!/usr/bin/env python
import sys
import time
import logging

from app.modules.dbutils.db_scheduler import update_scheduler_heartbeat

sys.path.insert(0, "/opt/NABS")
from app import app
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Настройка логирования в отдельный файл
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
    with app.app_context():
        from backuper import run_backup

        logger.info("Running scheduled backup")
        run_backup()


def load_job(scheduler):
    # Читаем настройки из БД
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
    # Создаём планировщик с хранилищем в БД (можно MemoryJobStore)
    # Если SSL проблема, добавьте ?sslmode=disable к URL
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if "sslmode" not in db_url:
        db_url += "?sslmode=disable"
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    scheduler = BackgroundScheduler(jobstores=jobstores, timezone="Europe/Moscow")

    # Загружаем задачу при старте
    job_config = load_job(scheduler)
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
        # первоначальная запись heartbeat
        update_scheduler_heartbeat()
    last_settings_hash = None

    # Цикл перечитывания настроек (каждые 60 секунд)
    try:
        # В начале файла, после импортов

        # В цикле while True:
        while True:
            time.sleep(60)
            with app.app_context():
                update_scheduler_heartbeat()

            new_config = load_job(scheduler)
            current_job = scheduler.get_job(JOB_ID)

            # Вычисляем хэш текущих настроек
            if new_config:
                if new_config['trigger'] == 'interval':
                    current_hash = hash(('interval', new_config.get('seconds')))
                else:
                    # Для cron-триггера используем строковое представление
                    current_hash = hash(('cron', str(new_config['trigger'])))
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
                    # Обновляем задачу только если изменились параметры
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
