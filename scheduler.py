# scheduler.py
import atexit
from typing import Optional
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler


_background_scheduler: Optional[BackgroundScheduler] = None


def init_scheduler(app) -> BackgroundScheduler:
    global _background_scheduler
    db_url = app.config['SQLALCHEMY_DATABASE_URI']
    jobstores = {'default': SQLAlchemyJobStore(url=db_url)}
    _background_scheduler = BackgroundScheduler(jobstores=jobstores, timezone='Europe/Moscow')
    _background_scheduler.app = app
    return _background_scheduler


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _background_scheduler


def scheduled_backup() -> None:
    from backuper import run_backup
    sched = get_scheduler()
    if sched is not None and hasattr(sched, 'app'):
        with sched.app.app_context():
            run_backup()


def shutdown_scheduler() -> None:
    sched = get_scheduler()
    if sched is not None and sched.running:
        sched.shutdown()


atexit.register(shutdown_scheduler)
