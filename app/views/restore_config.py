from flask import flash, redirect, request, url_for

from app.modules.auth.auth_users_ldap import check_auth


# Compatibility route. Restoring is done by the Restore Engine pages (restore_jobs.py);
# this old URL only forwards to the "new restore" page when it is given a device and a
# configuration, and otherwise explains where to start. It reads only the two ids from
# the request, touches neither the database nor a device, and changes nothing: a restore
# is never started from here, only after the explicit steps of the Restore pages.
@check_auth
def restore_config():
    device_id = request.values.get("device_id")
    config_id = request.values.get("config_id")
    if device_id and config_id:
        return redirect(
            url_for("restore_new", device_id=device_id, config_id=config_id)
        )
    flash(
        "Open a device's config page, choose a configuration and press Restore",
        "info",
    )
    return redirect(url_for("devices"))
