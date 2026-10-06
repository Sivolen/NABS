from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)

from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    get_all_cfg_timestamp_for_device,
    check_if_previous_configuration_exists,
    delete_config_for_device,
    get_last_env_for_device,
)
from app.modules.diff_context import get_diff_context_settings
from app.modules.access import can_access_device, parse_id


from app.modules.dbutils.db_user_rights import check_user_permission

from app import logger

from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_permission
# def diff_page(device_id):
#     """
#     This function render configs compare page
#     """
#     logger.info(
#         f"User: {session['user']} {session['rights']} opens the config compare page"
#     )
#     check_previous_config: bool = check_if_previous_configuration_exists(
#         device_id=device_id
#     )
#     config_timestamp: list = get_all_cfg_timestamp_for_device(device_id=device_id)
#     last_config_dict: dict = get_last_config_for_device(device_id=device_id)
#     device_environment: dict = get_last_env_for_device(device_id=device_id)
#
#     if request.method == "POST" and request.form.get("del_config_btn"):
#         config_id: str = request.form.get("del_config_btn")
#         result: bool = delete_config(config_id=config_id)
#         if not result:
#             logger.info(
#                 f"User: {session['user']} {session['rights']} tried to delete the"
#                 f" {config_id} configuration on the comparison page"
#             )
#             flash("Delete config error", "warning")
#             return redirect(f"/diff_page/{device_id}")
#
#         logger.info(
#             f"User: {session['user']} {session['rights']} removed the"
#             f" {config_id} configuration on the comparison page"
#         )
#         flash("Config has been deleted", "success")
#         return redirect(f"/diff_page/{device_id}")
#
#     if check_previous_config and last_config_dict is not None:
#         return render_template(
#             "diff_page.html",
#             last_config=last_config_dict["last_config"],
#             last_confog_id=last_config_dict["id"],
#             config_timestamp=config_timestamp,
#             timestamp=last_config_dict["timestamp"],
#             device_environment=device_environment,
#         )
#
#     if not check_previous_config and last_config_dict is not None:
#         flash("This device has no previous configuration ", "info")
#         return redirect(f"/config_page/{device_id}")
#
#     if not check_previous_config and last_config_dict is None:
#         flash("Device not found?", "info")
#         return redirect(url_for("devices"))
#
def diff_page(device_id):
    """Render config comparison page with basic checks"""
    user = session.get("user", "unknown")
    logger.info(f"User: {user} opens config compare for device {device_id}")

    try:
        check_previous = check_if_previous_configuration_exists(device_id)
        config_timestamps = get_all_cfg_timestamp_for_device(device_id)
        last_config = get_last_config_for_device(device_id) or {}
        device_env = get_last_env_for_device(device_id) or {}
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        flash("Data load error", "error")
        return redirect(url_for("devices"))

    # Del config
    if request.method == "POST" and "del_config_btn" in request.form:
        return handle_config_deletion(request.form["del_config_btn"], user, device_id)

    # Basic display logic
    if not last_config.get("last_config"):
        flash("Device config not found", "error")
        return redirect(url_for("devices"))

    if not check_previous:
        flash("No previous config", "info")
        return redirect(f"/config_page/{device_id}")

    return render_template(
        "diff_page.html",
        last_config=last_config.get("last_config", ""),
        last_config_id=last_config.get("id", 0),
        config_timestamp=config_timestamps,
        device_environment=device_env,
        timestamp=last_config.get("timestamp", ""),
        diff_context=get_diff_context_settings(device_env.get("device_vendor")),
    )


def handle_config_deletion(config_id, user, device_id):
    """
    Delete one configuration from the comparison page.

    Both ids come from the client (device_id from the URL, config_id from the form),
    so nothing is trusted: the user must be allowed to use THIS device, and the
    config is deleted only if it belongs to THIS device (one DELETE with both ids).
    A refused or failed request changes nothing and gets the same generic message.
    """
    device_id_int = parse_id(device_id)
    config_id_int = parse_id(config_id)
    if device_id_int is None or config_id_int is None:
        flash("Invalid config", "warning")
        return redirect(url_for("devices"))

    if not can_access_device(session, device_id_int):
        logger.warning(
            f"User {user} was refused to delete config {config_id_int}: no access to"
            f" device {device_id_int}"
        )
        flash("View config for this device is not allowed", "warning")
        return redirect(url_for("devices"))

    try:
        deleted = delete_config_for_device(
            config_id=config_id_int, device_id=device_id_int
        )
    except Exception as e:
        logger.error(f"Deletion error: {type(e).__name__}")
        flash("Server error", "danger")
        return redirect(f"/diff_page/{device_id_int}")

    if deleted:
        logger.info(
            f"User {user} deleted config {config_id_int} of device {device_id_int}"
        )
        flash("Config deleted", "success")
    else:
        logger.warning(
            f"User {user} failed to delete config {config_id_int} of device"
            f" {device_id_int}"
        )
        flash("Delete error", "warning")

    return redirect(f"/diff_page/{device_id_int}")


@check_auth
@check_user_permission
def compare_config(device_id: int):
    # check_previous_config: bool = check_if_previous_configuration_exists(
    #     device_id=device_id
    # )
    config_timestamp: list = get_all_cfg_timestamp_for_device(device_id=device_id)
    last_config_dict: dict = get_last_config_for_device(device_id=device_id)
    device_environment: dict = get_last_env_for_device(device_id=device_id)
    return render_template(
        "m.html",
        last_config=last_config_dict["last_config"],
        last_confog_id=last_config_dict["id"],
        config_timestamp=config_timestamp,
        timestamp=last_config_dict["timestamp"],
        device_environment=device_environment,
    )
