"""
Views for scheduler configuration and status API.
"""

import logging
from flask import render_template, request, flash, redirect, url_for, session, abort

from app import app
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.scheduler_manager import (
    get_scheduler_status,
    update_scheduler_job,
    get_scheduler_full_status,
)
from app.modules.dbutils.db_scheduler import (
    update_scheduler_settings,
    init_default_scheduler_settings,
)

logger = logging.getLogger(__name__)


@app.route("/scheduler/", methods=["GET", "POST"])
@check_auth
def scheduler_settings():
    """
    Scheduler configuration page.
    Only accessible by sadmin.
    """
    if session.get("rights") != "sadmin":
        logger.warning(
            f"User {session.get('user')} attempted to access scheduler without sadmin rights"
        )
        abort(403)

    # Ensure default settings exist in DB
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
            update_scheduler_job()  # Notifies the scheduler (no-op in standalone)
            flash(
                "Scheduler settings updated. Changes will take effect within a minute.",
                "success",
            )
            logger.info(
                f"Scheduler settings updated by {session.get('user')}: enabled={is_enabled}, type={trigger_type}"
            )
        else:
            flash("Failed to update scheduler settings.", "danger")
            logger.error(
                f"Failed to update scheduler settings by {session.get('user')}"
            )
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
    """
    API endpoint returning full scheduler status (enabled, running, active).
    Used by the sidebar status indicator.
    """
    return get_scheduler_full_status()
