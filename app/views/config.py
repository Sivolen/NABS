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
    get_all_cfg_timestamp_for_config_page,
    delete_config,
    get_last_env_for_device,
)
from app.modules.dbutils.db_user_rights import check_user_permission
from app import logger
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_permission
def config(device_id):
    """
    This function renders config page
    """
    logger.info(f"User: {session['user']} opens the config compare page")
    if request.method == "POST" and request.form.get("del_config_btn"):
        config_id = request.form.get("del_config_btn")
        result: bool = delete_config(config_id=config_id)
        if not result:
            flash("Delete config error", "warning")
            return redirect(url_for("config", device_id=device_id))
        print(device_id)
        flash("Config has been deleted", "success")
        return redirect(url_for("config", device_id=device_id))
        #
    previous_configs_timestamp = get_all_cfg_timestamp_for_device(device_id=device_id)
    config_timestamp_list = get_all_cfg_timestamp_for_config_page(device_id=device_id)
    last_config_dict = get_last_config_for_device(device_id=device_id)
    check_previous_config = check_if_previous_configuration_exists(device_id=device_id)
    device_environment = get_last_env_for_device(device_id=device_id)
    if last_config_dict is None:
        flash("Config not found?", "info")
        return redirect(url_for("devices", device_id=device_id))

    return render_template(
        "config_page.html",
        config_id=last_config_dict["id"],
        ipaddress=device_environment["device_ip"],
        last_config=last_config_dict["last_config"],
        timestamp=last_config_dict["timestamp"],
        config_timestamp_list=config_timestamp_list,
        check_previous_config=check_previous_config,
        previous_configs_timestamp=previous_configs_timestamp,
        device_environment=device_environment,
    )