from flask import render_template, request, flash, redirect, url_for, session, abort
from app import app
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.scheduler_manager import get_scheduler_status, update_scheduler_job
from app.modules.dbutils.db_scheduler import (
    update_scheduler_settings,
    init_default_scheduler_settings,
)
from app.modules.scheduler_manager import get_scheduler_full_status


@app.route("/scheduler/", methods=["GET", "POST"])
@check_auth
def scheduler_settings():
    if session.get("rights") != "sadmin":
        abort(403)

    init_default_scheduler_settings()

    if request.method == "POST":
        is_enabled = "is_enabled" in request.form
        trigger_type = request.form.get("trigger_type", "interval")
        interval_seconds = int(request.form.get("interval_seconds", 3600))
        cron_expression = request.form.get("cron_expression", "0 2 * * *")

        if trigger_type == "interval" and interval_seconds < 60:
            flash("Interval must be at least 60 seconds.", "warning")
            return redirect(url_for("scheduler_settings"))

        success = update_scheduler_settings(
            is_enabled, trigger_type, interval_seconds, cron_expression
        )
        if success:
            # Уведомляем планировщик об изменении (опционально)
            update_scheduler_job()
            flash(
                "Scheduler settings updated. Changes will take effect within a minute.",
                "success",
            )
        else:
            flash("Failed to update scheduler settings.", "danger")
        return redirect(url_for("scheduler_settings"))

    status = get_scheduler_status()
    return render_template(
        "scheduler.html",
        settings=status,
        settings_menu_active=True,
        scheduler_menu_active=True,
    )


@app.route("/api/scheduler_status")
@check_auth
def api_scheduler_status():
    return get_scheduler_full_status()
