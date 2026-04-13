# app/scheduler_setup.py
import os
from app import app
import scheduler
from app.modules.dbutils.db_scheduler import init_default_scheduler_settings
from app.modules.scheduler_manager import update_scheduler_job


def setup_scheduler():
    scheduler.init_scheduler(app)
    with app.app_context():
        init_default_scheduler_settings()
        update_scheduler_job()
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        sched = scheduler.get_scheduler()
        if sched:
            sched.start()
            app.logger.info("Scheduler started.")
