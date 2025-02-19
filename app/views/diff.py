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
    delete_config,
    get_last_env_for_device,
)


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
    )


def handle_config_deletion(config_id, user, device_id):
    """Simple deletion handler"""
    if not config_id.isdigit():
        flash("Invalid config", "warning")
        return redirect(f"/diff_page/{device_id}")

    try:
        if delete_config(config_id):
            logger.info(f"User {user} deleted config {config_id}")
            flash("Config deleted", "success")
        else:
            logger.warning(f"Delete failed for config {config_id}")
            flash("Delete error", "warning")
    except Exception as e:
        logger.error(f"Deletion error: {str(e)}")
        flash("Server error", "danger")

    return redirect(f"/diff_page/{device_id}")


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
