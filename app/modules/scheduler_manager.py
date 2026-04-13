import subprocess
from app import app
from app.modules.dbutils.db_scheduler import get_scheduler_settings


def update_scheduler_job():
    # Не используется при отдельном процессе
    pass


def is_scheduler_running() -> bool:
    try:
        # Проверяем, есть ли процесс scheduler_runner.py
        result = subprocess.run(
            ["pgrep", "-f", "scheduler_runner.py"], capture_output=True
        )
        return result.returncode == 0
    except Exception:
        return False


def get_scheduler_status():
    with app.app_context():
        settings = get_scheduler_settings()
        scheduler_active = is_scheduler_running()
        return {
            "is_enabled": settings.is_enabled if settings else False,
            "trigger_type": settings.trigger_type if settings else "interval",
            "interval_seconds": settings.interval_seconds if settings else 3600,
            "cron_expression": settings.cron_expression if settings else "0 2 * * *",
            "scheduler_running": scheduler_active,
        }


def get_scheduler_full_status():
    with app.app_context():
        settings = get_scheduler_settings()
        enabled = settings.is_enabled if settings else False
        running = is_scheduler_running()
        return {"enabled": enabled, "running": running, "active": enabled and running}
