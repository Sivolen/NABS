import atexit
from typing import Optional
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from app import logger

_background_scheduler: Optional[BackgroundScheduler] = None


def init_scheduler(app):
    global _background_scheduler
    jobstores = {"default": MemoryJobStore()}
    _background_scheduler = BackgroundScheduler(
        jobstores=jobstores, timezone="Europe/Moscow"
    )
    _background_scheduler.app = app
    return _background_scheduler


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _background_scheduler


def scheduled_backup():
    logger.info("=== scheduled_backup started ===")
    from backuper import run_backup

    sched = get_scheduler()
    if sched is not None and hasattr(sched, "app"):
        with sched.app.app_context():
            run_backup()
    logger.info("=== scheduled_backup finished ===")


def shutdown_scheduler():
    sched = get_scheduler()
    if sched is not None and sched.running:
        sched.shutdown()


atexit.register(shutdown_scheduler)
