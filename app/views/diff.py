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
def diff_page(device_id):
    """
    This function render configs compare page
    """
    logger.info(
        f"User: {session['user']} {session['rights']} opens the config compare page"
    )
    check_previous_config: bool = check_if_previous_configuration_exists(
        device_id=device_id
    )
    config_timestamp: list = get_all_cfg_timestamp_for_device(device_id=device_id)
    last_config_dict: dict = get_last_config_for_device(device_id=device_id)
    device_environment: dict = get_last_env_for_device(device_id=device_id)

    if request.method == "POST" and request.form.get("del_config_btn"):
        config_id: str = request.form.get("del_config_btn")
        result: bool = delete_config(config_id=config_id)
        if not result:
            logger.info(
                f"User: {session['user']} {session['rights']} tried to delete the"
                f" {config_id} configuration on the comparison page"
            )
            flash("Delete config error", "warning")
            return redirect(f"/diff_page/{device_id}")

        logger.info(
            f"User: {session['user']} {session['rights']} removed the"
            f" {config_id} configuration on the comparison page"
        )
        flash("Config has been deleted", "success")
        return redirect(f"/diff_page/{device_id}")

    if check_previous_config and last_config_dict is not None:
        return render_template(
            "diff_page.html",
            last_config=last_config_dict["last_config"],
            last_confog_id=last_config_dict["id"],
            config_timestamp=config_timestamp,
            timestamp=last_config_dict["timestamp"],
            device_environment=device_environment,
        )

    if not check_previous_config and last_config_dict is not None:
        flash("This device has no previous configuration ", "info")
        return redirect(f"/config_page/{device_id}")

    if not check_previous_config and last_config_dict is None:
        flash("Device not found?", "info")
        return redirect(url_for("devices"))


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
