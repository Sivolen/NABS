# app/modules/scheduler_manager.py
from app import app
from app.modules.dbutils.db_scheduler import get_scheduler_settings
import scheduler
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)
JOB_ID = "backup_job"


def update_scheduler_job():
    with app.app_context():
        settings = get_scheduler_settings()
        sched = scheduler.get_scheduler()
        if sched is None:
            logger.error("Scheduler not initialized")
            return

        if sched.get_job(JOB_ID):
            sched.remove_job(JOB_ID)

        if not settings or not settings.is_enabled:
            logger.info("Scheduler disabled, job removed")
            return

        # Общие параметры для защиты от перекрытия
        job_params = {
            'id': JOB_ID,
            'func': scheduler.scheduled_backup,
            'replace_existing': True,
            'max_instances': 1,
            'coalesce': True,
            'misfire_grace_time': 3600
        }

        if settings.trigger_type == 'interval':
            sched.add_job(
                trigger='interval',
                seconds=settings.interval_seconds,
                **job_params
            )
            logger.info(f"Added interval job: {settings.interval_seconds}s")
        elif settings.trigger_type == 'cron':
            trigger = CronTrigger.from_crontab(settings.cron_expression)
            sched.add_job(
                trigger=trigger,
                **job_params
            )
            logger.info(f"Added cron job: {settings.cron_expression}")


def get_scheduler_status():
    """
    Возвращает настройки планировщика из БД.
    """
    with app.app_context():
        settings = get_scheduler_settings()
        return {
            'is_enabled': settings.is_enabled if settings else False,
            'trigger_type': settings.trigger_type if settings else 'interval',
            'interval_seconds': settings.interval_seconds if settings else 3600,
            'cron_expression': settings.cron_expression if settings else '0 2 * * *',
            'job_exists': None,   # неизвестно, т.к. планировщик в отдельном процессе
            'next_run_time': None
        }
