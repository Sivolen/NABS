import atexit
from typing import Optional
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from app import logger

_background_scheduler: Optional[BackgroundScheduler] = None


def init_scheduler(app) -> BackgroundScheduler:
    """
    Initializes the global background scheduler with MemoryJobStore.

    Args:
        app: Flask application instance (used to store app reference for context).

    Returns:
        BackgroundScheduler instance.
    """
    global _background_scheduler
    jobstores = {"default": MemoryJobStore()}
    _background_scheduler = BackgroundScheduler(
        jobstores=jobstores, timezone="Europe/Moscow"
    )
    _background_scheduler.app = app
    return _background_scheduler


def get_scheduler() -> Optional[BackgroundScheduler]:
    """Returns the global scheduler instance or None if not initialized."""
    return _background_scheduler


def scheduled_backup() -> None:
    """
    Wrapper function to run backup within the application context.
    Called by the scheduler (if used directly, but currently tasks are handled by scheduler_runner.py).
    """
    logger.info("=== scheduled_backup started ===")
    sched = get_scheduler()
    if sched is None or not hasattr(sched, "app"):
        logger.warning("Scheduler not properly initialized, cannot run backup")
        return

    from backuper import run_backup

    with sched.app.app_context():  # type: ignore[attr-defined]
        run_backup()

    logger.info("=== scheduled_backup finished ===")


def shutdown_scheduler() -> None:
    """Shuts down the global scheduler if it is running."""
    sched = get_scheduler()
    if sched is not None and sched.running:
        sched.shutdown()


atexit.register(shutdown_scheduler)
